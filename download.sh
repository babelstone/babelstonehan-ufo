#!/bin/sh

curl --remote-name --remote-header-name --location https://www.babelstone.co.uk/Fonts/Download/BabelStoneHanBeta.zip
unzip -o BabelStoneHanBeta.zip
rm BabelStoneHanBeta.zip

curl --remote-name --remote-header-name --location https://www.babelstone.co.uk/Fonts/Download/BabelStoneHanPUA.ttf