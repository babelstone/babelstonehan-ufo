//! Write the glyphs layer of a UFO from a TrueType font, byte-for-byte the way
//! extractufo (fontTools' ufoLib) does.
//!
//! Usage: ttf2ufo <font.ttf> <font.ufo>
//!
//! Only `<font.ufo>/glyphs/` is written; the rest of the UFO comes from
//! `extract_info.py`. The glyphs are updated in place: every file is generated
//! in memory first, then only files whose content changed are rewritten and
//! .glif files for glyphs that no longer exist are removed, so unchanged files
//! keep their mtime and git does not have to re-hash them.
//!
//! Set TTF2UFO_TIMING=1 to print how long each stage takes.
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::error::Error;
use std::fmt::Write as _;
use std::path::Path;

use rayon::prelude::*;
use read_fonts::tables::glyf::Glyph as TtGlyph;
use read_fonts::types::GlyphId;
use read_fonts::{FontRef, TableProvider};
use sha2::{Digest, Sha512};

type Result<T> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

const XML_DECL: &str = "<?xml version='1.0' encoding='UTF-8'?>\n";
const PLIST_HEAD: &str = "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\">\n";

/// Escape text content the way fontTools (etree / plistlib) does.
fn esc_text(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

/// Escape an attribute value the way fontTools' etree does.
fn esc_attr(s: &str) -> String {
    esc_text(s)
        .replace('"', "&quot;")
        .replace('\n', "&#10;")
        .replace('\r', "&#13;")
        .replace('\t', "&#09;")
}

/// fontTools.misc.filenames.userNameToFileName with suffix ".glif".
fn glyph_file_name(name: &str, existing_lower: &mut HashSet<String>) -> String {
    const ILLEGAL: &[char] = &['"', '*', '+', '/', ':', '<', '>', '?', '[', '\\', ']', '|', '\0'];
    const RESERVED: &[&str] = &[
        "con", "prn", "aux", "clock$", "nul", "a:-z:", "com1", "lpt1", "lpt2", "lpt3", "com2",
        "com3", "com4",
    ];
    let mut user = name.to_string();
    if user.starts_with('.') {
        user = format!("_{}", &user[1..]);
    }
    let mut filtered = String::new();
    for c in user.chars() {
        if ILLEGAL.contains(&c) || (c as u32) < 32 || c as u32 == 0x7F {
            filtered.push('_');
        } else {
            filtered.push(c);
            if c.to_lowercase().collect::<String>() != c.to_string() {
                filtered.push('_');
            }
        }
    }
    let base: String = filtered
        .split('.')
        .map(|part| {
            if RESERVED.contains(&part.to_lowercase().as_str()) {
                format!("_{part}")
            } else {
                part.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join(".");
    let base: String = base.chars().take(255 - ".glif".len()).collect();
    let mut file = format!("{base}.glif");
    if existing_lower.contains(&file.to_lowercase()) {
        // handleClash1: 15-digit counter between name and suffix
        let mut n = 1u64;
        loop {
            let cand = format!("{base}{n:015}.glif");
            if !existing_lower.contains(&cand.to_lowercase()) {
                file = cand;
                break;
            }
            n += 1;
        }
    }
    existing_lower.insert(file.to_lowercase());
    file
}

/// Minimal plist value, enough for what extractufo writes in the glyphs layer.
enum PV {
    Str(String),
    Dict(Vec<(String, PV)>), // written sorted by key, as fontTools sorts dict keys
}

fn write_plist_value(out: &mut String, v: &PV, indent: usize) {
    let pad = "  ".repeat(indent);
    match v {
        PV::Str(s) => writeln!(out, "{pad}<string>{}</string>", esc_text(s)).unwrap(),
        PV::Dict(items) if items.is_empty() => writeln!(out, "{pad}<dict/>").unwrap(),
        PV::Dict(items) => {
            writeln!(out, "{pad}<dict>").unwrap();
            let mut sorted: Vec<_> = items.iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(&b.0));
            for (k, val) in sorted {
                writeln!(out, "{pad}  <key>{}</key>", esc_text(k)).unwrap();
                write_plist_value(out, val, indent + 1);
            }
            writeln!(out, "{pad}</dict>").unwrap();
        }
    }
}

fn plist_file(root: &PV) -> String {
    let mut s = String::from(XML_DECL);
    s.push_str(PLIST_HEAD);
    write_plist_value(&mut s, root, 1);
    s.push_str("</plist>\n");
    s
}

/// Render one glyph as .glif text, matching fontTools' glifLib output.
fn glif(
    font: &FontRef,
    gid: u32,
    name: &str,
    unicodes: Option<&BTreeSet<u32>>,
) -> Result<String> {
    let glyf = font.glyf()?;
    let loca = font.loca(None)?;
    let hmtx = font.hmtx()?;
    let id = GlyphId::new(gid);
    let width = hmtx.advance(id).unwrap_or(0);
    let lsb = hmtx.side_bearing(id).unwrap_or(0) as i32;

    let mut s = String::with_capacity(8192);
    s.push_str(XML_DECL);
    writeln!(s, "<glyph name=\"{}\" format=\"2\">", esc_attr(name))?;
    if width != 0 {
        writeln!(s, "  <advance width=\"{width}\"/>")?;
    }
    for u in unicodes.into_iter().flatten() {
        writeln!(s, "  <unicode hex=\"{u:04X}\"/>")?;
    }
    s.push_str("  <outline>\n");

    // fontTools.pens.hashPointPen.HashPointPen pre-image of the outline
    let mut hash_data = format!("w{width}");
    let mut has_program = false;
    match loca.get_glyf(id, &glyf)? {
        None => {}
        Some(TtGlyph::Composite(_)) => {
            return Err(format!("{name}: composite glyphs are not supported").into());
        }
        Some(TtGlyph::Simple(g)) => {
            has_program = true;
            if !g.instructions().is_empty() {
                return Err(format!("{name}: glyph instructions are not supported").into());
            }
            // fontTools' glyph set shifts x by (hmtx lsb - stored xMin)
            let offset = lsb - g.x_min() as i32;
            let pts: Vec<_> = g.points().collect();
            let mut start = 0usize;
            for end in g.end_pts_of_contours() {
                let end = end.get() as usize + 1;
                let contour = pts.get(start..end).ok_or_else(|| format!("{name}: bad contour"))?;
                start = end;
                s.push_str("    <contour>\n");
                let mut seg = if contour.last().is_some_and(|p| p.on_curve) {
                    "line"
                } else {
                    "qcurve"
                };
                for p in contour {
                    let (x, y) = (p.x as i32 + offset, p.y as i32);
                    if p.on_curve {
                        writeln!(s, "      <point x=\"{x}\" y=\"{y}\" type=\"{seg}\"/>")?;
                        write!(hash_data, "{}{x}{y:+}", &seg[..1])?;
                        seg = "line";
                    } else {
                        writeln!(s, "      <point x=\"{x}\" y=\"{y}\"/>")?;
                        write!(hash_data, "o{x}{y:+}")?;
                        seg = "qcurve";
                    }
                }
                hash_data.push('|');
                s.push_str("    </contour>\n");
            }
        }
    }
    s.push_str("  </outline>\n");

    if has_program {
        let id = if hash_data.len() >= 128 {
            Sha512::digest(hash_data.as_bytes()).iter().fold(String::with_capacity(128), |mut h, b| {
                let _ = write!(h, "{b:02x}");
                h
            })
        } else {
            hash_data
        };
        let lib = PV::Dict(vec![(
            "public.truetype.instructions".into(),
            PV::Dict(vec![
                ("assembly".into(), PV::Str("\n\n".into())),
                ("formatVersion".into(), PV::Str("1".into())),
                ("id".into(), PV::Str(id)),
            ]),
        )]);
        s.push_str("  <lib>\n");
        write_plist_value(&mut s, &lib, 2);
        s.push_str("  </lib>\n");
    }
    s.push_str("</glyph>\n");
    Ok(s)
}

/// Write `content` to `path` unless the file already holds exactly that.
fn write_if_changed(path: &Path, content: &[u8]) -> Result<bool> {
    match std::fs::read(path) {
        Ok(old) if old == content => Ok(false),
        _ => {
            std::fs::write(path, content)?;
            Ok(true)
        }
    }
}

fn run(font_path: &Path, ufo: &Path) -> Result<()> {
    let t0 = std::time::Instant::now();
    let timing = std::env::var_os("TTF2UFO_TIMING").is_some();
    let lap = |what: &str| if timing { eprintln!("{:>8.3}s {what}", t0.elapsed().as_secs_f64()) };
    let data = std::fs::read(font_path)?;
    let font = FontRef::new(&data)?;
    let post = font.post()?;
    let cmap = font.cmap()?;
    let num_glyphs = font.maxp()?.num_glyphs() as u32;

    // codepoints per glyph, union over all cmap subtables (like cmap.buildReversed())
    let mut rev: BTreeMap<u32, BTreeSet<u32>> = BTreeMap::new();
    for i in 0..cmap.encoding_records().len() {
        if let Ok(sub) = cmap.subtable(i as u16) {
            for (cp, gid) in sub.iter() {
                // skip the format 4 end-of-table sentinel (U+FFFF -> .notdef), as fontTools does
                if cp == 0xFFFF && gid.to_u32() == 0 {
                    continue;
                }
                rev.entry(gid.to_u32()).or_default().insert(cp);
            }
        }
    }

    // glyph names and file names (sequential: file-name clashes depend on order)
    let mut seen_names = HashSet::new();
    let mut seen_files = HashSet::new();
    // post.glyph_name() scans the string data from the start on every call,
    // which is quadratic over ~40k glyphs; read all names in one pass instead.
    let mut post_names: Vec<Option<&str>> = vec![None; num_glyphs as usize];
    for (gid, name) in post.glyph_names() {
        if let Some(slot) = post_names.get_mut(gid.to_u32() as usize) {
            *slot = Some(name);
        }
    }
    let mut glyphs = Vec::with_capacity(num_glyphs as usize);
    for gid in 0..num_glyphs {
        let name = post_names[gid as usize]
            .map(str::to_string)
            .unwrap_or_else(|| format!("glyph{gid:05}"));
        if !seen_names.insert(name.clone()) {
            return Err(format!("duplicate glyph name {name:?} is not supported").into());
        }
        let file = glyph_file_name(&name, &mut seen_files);
        glyphs.push((gid, name, file));
    }

    lap("names");
    // generate every .glif in parallel before touching the UFO
    let rendered: Vec<String> = glyphs
        .par_iter()
        .map(|(gid, name, _)| glif(&font, *gid, name, rev.get(gid)))
        .collect::<Result<_>>()?;
    let contents = plist_file(&PV::Dict(
        glyphs.iter().map(|(_, name, file)| (name.clone(), PV::Str(file.clone()))).collect(),
    ));

    lap("render");
    let dir = ufo.join("glyphs");
    std::fs::create_dir_all(&dir)?;
    let written = glyphs
        .par_iter()
        .zip(rendered.par_iter())
        .map(|((_, _, file), text)| write_if_changed(&dir.join(file), text.as_bytes()))
        .collect::<Result<Vec<bool>>>()?
        .into_iter()
        .filter(|w| *w)
        .count();
    lap("compare/write");
    let wanted: HashSet<&str> = glyphs.iter().map(|(_, _, f)| f.as_str()).collect();
    let mut removed = 0;
    for entry in std::fs::read_dir(&dir)? {
        let path = entry?.path();
        let file = path.file_name().and_then(|f| f.to_str()).unwrap_or_default();
        if file.ends_with(".glif") && !wanted.contains(file) {
            std::fs::remove_file(&path)?;
            removed += 1;
        }
    }
    lap("remove stale");
    let contents_changed = write_if_changed(&dir.join("contents.plist"), contents.as_bytes())?;

    println!(
        "{}: {num_glyphs} glyphs, {written} written, {removed} removed{}",
        ufo.display(),
        if contents_changed { ", contents.plist updated" } else { "" }
    );
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: ttf2ufo <font.ttf> <font.ufo>");
        std::process::exit(2);
    }
    if let Err(e) = run(Path::new(&args[1]), Path::new(&args[2])) {
        eprintln!("ttf2ufo: {}: {e}", args[1]);
        std::process::exit(1);
    }
}
