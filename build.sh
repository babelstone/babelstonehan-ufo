#!/bin/sh
rm -r *.ufo
for name in BabelStoneHanBasic.ttf BabelStoneHanExtra.ttf BabelStoneHanPUA.ttf
do
    extractufo "${name}"
done