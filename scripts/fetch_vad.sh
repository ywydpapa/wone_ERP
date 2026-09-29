#!/bin/bash
# vad-web + onnxruntime-web을 npm pack으로 받아서 필요한 파일만 복사
set -eu
DEST=static/vendor/vad
TMP=$(mktemp -d)
mkdir -p "$DEST" "$TMP/vad" "$TMP/ort"

npm pack @ricky0123/vad-web@0.0.31 --pack-destination "$TMP"
npm pack onnxruntime-web@1.30.0 --pack-destination "$TMP"

tar -xzf "$TMP"/ricky0123-vad-web-0.0.31.tgz -C "$TMP/vad"
tar -xzf "$TMP"/onnxruntime-web-1.30.0.tgz -C "$TMP/ort"

cp "$TMP/vad/package/dist/bundle.min.js" "$DEST/"
cp "$TMP/vad/package/dist/vad.worklet.bundle.min.js" "$DEST/"
cp "$TMP/vad/package/dist/silero_vad_v5.onnx" "$DEST/"
cp "$TMP/ort/package/dist/ort.wasm.min.js" "$DEST/"
cp "$TMP/ort/package/dist/ort-wasm-simd-threaded.wasm" "$DEST/"
cp "$TMP/ort/package/dist/ort-wasm-simd-threaded.mjs" "$DEST/"

rm -rf "$TMP"
echo "vad 자산을 $DEST 에 복사했습니다"
