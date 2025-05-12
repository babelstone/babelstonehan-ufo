#!/bin/sh
rm -r *.ufo
for name in *.ttf
do
    extractufo "${name}"
done