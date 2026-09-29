# 망분리 배포 전에 인터넷 되는 곳에서 한 번 실행해서 모델 받아두기
from huggingface_hub import snapshot_download

snapshot_download(
    "supertone-oss-archive/supertonic-3",
    revision="aafc6e32416a594460b32413efc49d7fe4ce6d46",
    local_dir="models/supertonic",
)
print("ok")
