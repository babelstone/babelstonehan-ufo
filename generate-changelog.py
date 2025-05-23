#!/usr/bin/env python3

import subprocess
import sys
import xml.etree.ElementTree as ET
import argparse
from pathlib import Path
import urllib.parse

class UFOChangelogGenerator:
    def __init__(self):
        self.ufo_dirs = [
            "BabelStoneHanBasic.ttf.ufo",
            "BabelStoneHanExtra.ttf.ufo", 
            "BabelStoneHanPUA.ttf.ufo"
        ]
        self.github_repo = "https://github.com/babelstone/babelstonehan-ufo"
        
    def run_git_command(self, cmd):
        """Run a git command and return the output."""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error running git command: {cmd}", file=sys.stderr)
            print(f"Error: {e.stderr}", file=sys.stderr)
            return ""
    
    def get_latest_tags(self):
        """Get the latest 2 tags."""
        tags_output = self.run_git_command("git tag --sort=-version:refname")
        if not tags_output:
            print("Error: No tags found in repository", file=sys.stderr)
            sys.exit(1)
            
        tags = tags_output.split('\n')
        if len(tags) < 2:
            print(f"Error: Need at least 2 tags to compare. Found only {len(tags)} tag(s).", file=sys.stderr)
            sys.exit(1)
            
        return tags[0], tags[1]  # newest, previous
    
    def validate_tag(self, tag):
        """Validate that a tag exists."""
        result = self.run_git_command(f"git rev-parse --verify {tag}")
        return bool(result)
    
    def extract_glyph_name_from_path(self, file_path):
        """Extract glyph name from .glif file path."""
        if file_path.endswith('.glif'):
            return Path(file_path).stem
        return None
    
    def infer_unicode_from_glyph_name(self, glyph_name):
        return glyph_name.replace("uni", "").replace("u", "").replace("_", "")

    def get_unicode_from_glif(self, tag, file_path):
        """Extract Unicode value from a .glif file."""
        try:
            content = self.run_git_command(f"git show {tag}:{file_path}")
            if not content:
                return None
                
            try:
                root = ET.fromstring(content)
                unicode_elem = root.find('.//unicode')
                if unicode_elem is not None and 'hex' in unicode_elem.attrib:
                    hex_val = unicode_elem.attrib['hex']
                    return hex_val.upper()
            except ET.ParseError:
                pass
                
        except Exception:
            pass
        return None
    
    def get_glyph_changes_for_ufo(self, ufo_dir, from_tag, to_tag):
        """Get glyph changes for a specific UFO directory."""
        changes = {
            'added': [],
            'modified': [],
            'removed': []
        }
        
        # Get file changes within this UFO directory
        diff_cmd = f"git diff --name-status {from_tag}..{to_tag} -- '{ufo_dir}/glyphs/*.glif'"
        diff_output = self.run_git_command(diff_cmd)
        
        if not diff_output:
            return changes
            
        for line in diff_output.split('\n'):
            if not line.strip():
                continue
                
            parts = line.split('\t', 1)
            if len(parts) != 2:
                continue
                
            status, file_path = parts
            glyph_name = self.extract_glyph_name_from_path(file_path)
            
            if not glyph_name:
                continue
                
            if status == 'A':  # Added
                unicode_info = self.get_unicode_from_glif(to_tag, file_path)
                changes['added'].append({
                    'name': glyph_name,
                    'unicode': unicode_info,
                    'path': file_path,
                })
            elif status == 'M':  # Modified
                unicode_info = self.get_unicode_from_glif(to_tag, file_path)
                changes['modified'].append({
                    'name': glyph_name,
                    'unicode': unicode_info,
                    'path': file_path,
                })
            elif status == 'D':  # Deleted
                unicode_info = self.get_unicode_from_glif(from_tag, file_path)
                changes['removed'].append({
                    'name': glyph_name,
                    'unicode': unicode_info,
                    'path': file_path,
                })
        
        # Sort all changes by glyph name
        for change_type in changes:
            changes[change_type].sort(key=lambda x: x['name'])
            
        return changes
    
    def get_ufo_structure_changes(self, ufo_dir, from_tag, to_tag):
        """Get changes to UFO structure files."""
        structure_files = [
            'groups.plist', 
            'kerning.plist',
            'layercontents.plist',
            'metainfo.plist'
        ]
        
        changed_files = []
        for struct_file in structure_files:
            file_path = f"{ufo_dir}/{struct_file}"
            diff_cmd = f"git diff --name-only {from_tag}..{to_tag} -- {file_path}"
            if self.run_git_command(diff_cmd):
                if self.github_repo:
                    encoded_path = urllib.parse.quote(file_path)
                    link = f"[{struct_file}]({self.github_repo}/blob/{to_tag}/{encoded_path})"
                    changed_files.append(link)
                else:
                    changed_files.append(struct_file)
                
        return changed_files
    
    def get_glyph_counts(self, ufo_dir, tag):
        """Get total glyph count for a UFO at a specific tag."""
        cmd = f"git ls-tree -r --name-only {tag} -- {ufo_dir}/glyphs/ | grep -c '\\.glif$' || echo '0'"
        result = self.run_git_command(cmd)
        return int(result) if result.isdigit() else 0
    
    def get_tag_date(self, tag):
        """Get the date of a tag."""
        date_cmd = f"git log -1 --format=%ad --date=short {tag}"
        return self.run_git_command(date_cmd)
    
    def format_glyph_list(self, glyphs, max_display=150):
        """Format a list of glyphs for display with GitHub links."""
        if not glyphs:
            return "None"
            
        output = []
        for i, glyph in enumerate(glyphs):
            if i >= max_display:
                remaining = len(glyphs) - max_display
                output.append(f"*... and {remaining} more glyphs*")
                break
                
            if glyph['unicode']:
                output.append(f"- U+{glyph['unicode']} {chr(int(glyph['unicode'], 16))}")
                if glyph['unicode'] != self.infer_unicode_from_glyph_name(glyph['name']):
                    # Output glyph name if the unicode value is not as same as the inferred unicode value
                    output.append(f" (`{glyph['name']}`)")
            else:
                output.append(f"- `{glyph['name']}`")
                
        return "\n".join(output)
    
    def generate_combined_changelog(self, from_tag, to_tag):
        """Generate a single changelog showing all three UFO changes."""
        print(f"Analyzing all UFOs from {from_tag} to {to_tag}...", file=sys.stderr)
        
        # Get tag date
        tag_date = self.get_tag_date(to_tag)
        
        # Collect data for all UFOs
        all_changes = {}
        total_stats = {'added': 0, 'modified': 0, 'removed': 0}
        
        for ufo_dir in self.ufo_dirs:
            changes = self.get_glyph_changes_for_ufo(ufo_dir, from_tag, to_tag)
            structure_changes = self.get_ufo_structure_changes(ufo_dir, from_tag, to_tag)
            
            old_count = self.get_glyph_counts(ufo_dir, from_tag)
            new_count = self.get_glyph_counts(ufo_dir, to_tag)
            
            ufo_name = ufo_dir.replace('.ttf.ufo', '')
            all_changes[ufo_name] = {
                'changes': changes,
                'structure_changes': structure_changes,
                'old_count': old_count,
                'new_count': new_count,
                'ufo_dir': ufo_dir
            }
            
            total_stats['added'] += len(changes['added'])
            total_stats['modified'] += len(changes['modified'])
            total_stats['removed'] += len(changes['removed'])
        
        # Generate combined changelog
        changelog = f"""## {to_tag} - {tag_date}

### Summary

Changes from `{from_tag}` to `{to_tag}` across all BabelStone Han UFO files.

**Family Totals:** {total_stats['added']} added, {total_stats['modified']} modified, {total_stats['removed']} removed ({sum(total_stats.values())} total changes)
"""

        # Add details for each UFO
        for ufo_name, data in all_changes.items():
            changes = data['changes']
            structure_changes = data['structure_changes']
            old_count = data['old_count']
            new_count = data['new_count']
            glyph_diff = new_count - old_count
            
            changelog += f"""
### {ufo_name.replace("BabelStoneHan", "BabelStone Han ")}

**Glyph Statistics:** {old_count:,} → {new_count:,} glyphs ({glyph_diff:+,})
"""
            if (changes['added']):
                changelog += f"""
#### ✅ Added Glyphs ({len(changes['added'])})
{self.format_glyph_list(changes['added'])}
"""
            if (changes['modified']):
                changelog += f"""
#### ✏️ Modified Glyphs ({len(changes['modified'])})
{self.format_glyph_list(changes['modified'])}
"""
            if (changes['removed']):
                changelog += f"""
#### ❌ Removed Glyphs ({len(changes['removed'])})
{self.format_glyph_list(changes['removed'])}
"""
            if structure_changes:
                changelog += f"""
#### 📝 Structure Changes
{', '.join(structure_changes)}
"""
        
        # Add links
        changelog += f"""
---

### Links

- **Full diff:** [{from_tag}...{to_tag}]({self.github_repo}/compare/{from_tag}...{to_tag})
- **PUA List:** https://www.babelstone.co.uk/Fonts/PUA.html

"""
        
        return changelog

def main():
    parser = argparse.ArgumentParser(
        description='Generate UFO changelog for BabelStone Han fonts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Compare latest two tags
  %(prog)s --from v1.0 --to v1.1     # Compare specific tags
  %(prog)s --to HEAD                 # Compare latest tag to HEAD
        """
    )
    parser.add_argument('--from', dest='from_tag', 
                       help='Tag to compare from (default: second latest tag)')
    parser.add_argument('--to', dest='to_tag',
                       help='Tag to compare to (default: latest tag)')
    
    args = parser.parse_args()
    
    # Initialize generator
    generator = UFOChangelogGenerator()
    
    # Check if we're in a git repository
    if not generator.run_git_command("git rev-parse --git-dir"):
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)
    
    # Determine tags to compare
    if args.from_tag and args.to_tag:
        from_tag, to_tag = args.from_tag, args.to_tag
    elif args.to_tag:
        # Get previous tag before to_tag
        tags_before = generator.run_git_command(f"git tag --sort=-version:refname --merged {args.to_tag}")
        if not tags_before:
            print(f"Error: No tags found before {args.to_tag}", file=sys.stderr)
            sys.exit(1)
        tags_list = [t for t in tags_before.split('\n') if t != args.to_tag]
        if not tags_list:
            print(f"Error: No previous tag found before {args.to_tag}", file=sys.stderr)
            sys.exit(1)
        from_tag, to_tag = tags_list[0], args.to_tag
    elif args.from_tag:
        # Get next tag after from_tag
        all_tags = generator.run_git_command("git tag --sort=version:refname")
        tags_list = all_tags.split('\n')
        try:
            from_idx = tags_list.index(args.from_tag)
            if from_idx + 1 >= len(tags_list):
                print(f"Error: No tag found after {args.from_tag}", file=sys.stderr)
                sys.exit(1)
            from_tag, to_tag = args.from_tag, tags_list[from_idx + 1]
        except ValueError:
            print(f"Error: Tag {args.from_tag} not found", file=sys.stderr)
            sys.exit(1)
    else:
        # Use latest two tags
        to_tag, from_tag = generator.get_latest_tags()
    
    # Validate tags
    if not generator.validate_tag(from_tag):
        print(f"Error: Tag '{from_tag}' does not exist", file=sys.stderr)
        sys.exit(1)
    if not generator.validate_tag(to_tag):
        print(f"Error: Tag '{to_tag}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    print(f"Generating changelog from {from_tag} to {to_tag}...", file=sys.stderr)
    if generator.github_repo:
        print(f"GitHub repository: {generator.github_repo}", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Generate and output changelog
    changelog = generator.generate_combined_changelog(from_tag, to_tag)
    print(changelog)

if __name__ == "__main__":
    main()