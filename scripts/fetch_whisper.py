# 망분리 배포 전에 인터넷 되는 곳에서 한 번 실행해서 모델 캐시 받아두기
from faster_whisper import WhisperModel

WhisperModel("small", device="cpu", compute_type="int8")
print("ok")
