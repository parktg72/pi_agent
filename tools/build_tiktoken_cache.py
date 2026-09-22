"""
tiktoken 오프라인 캐시 생성기 (네트워크 불필요)

출처: 폐쇄망지식그래프/07_scripts/build_tiktoken_cache.py (2026-09-22). install-kg.bat이 부른다.
아래 URL은 캐시 파일 이름(URL의 sha1)을 만드는 데만 쓰고 접속하지 않는다.

02_tiktoken_cache/*.tiktoken 원본 파일을 tiktoken이 기대하는 SHA1 파일명으로
캐시 디렉터리에 복사한다.

사용법:
    python build_tiktoken_cache.py [--src ..\\02_tiktoken_cache] [--dst %USERPROFILE%\\.tiktoken_cache]

이후 환경변수 설정:
    setx TIKTOKEN_CACHE_DIR "%USERPROFILE%\\.tiktoken_cache"
"""
import argparse
import hashlib
import os
import shutil
import sys

# tiktoken은 원본 URL의 sha1 hexdigest를 캐시 파일명으로 쓴다.
ENCODINGS = {
    "cl100k_base": "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken",
    "o200k_base": "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken",
}


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(here, "..", "02_tiktoken_cache"))
    ap.add_argument("--dst", default=os.path.join(os.path.expanduser("~"), ".tiktoken_cache"))
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    dst = os.path.abspath(args.dst)
    os.makedirs(dst, exist_ok=True)

    ok = 0
    for name, url in ENCODINGS.items():
        srcfile = os.path.join(src, f"{name}.tiktoken")
        if not os.path.exists(srcfile):
            print(f"[skip] {srcfile} 없음")
            continue
        key = hashlib.sha1(url.encode()).hexdigest()
        target = os.path.join(dst, key)
        shutil.copyfile(srcfile, target)
        print(f"[ok] {name} -> {target}")
        ok += 1

    if ok != len(ENCODINGS):
        # 하나라도 빠지면 그 인코딩을 쓰는 순간 tiktoken이 원본 URL로 받으려 한다(폐쇄망에서 실패).
        print(f"{len(ENCODINGS)}개 중 {ok}개만 복사했습니다. --src 경로를 확인하세요.")
        return 1

    print()
    print(f"캐시 디렉터리: {dst}")
    print(f'환경변수 설정:  setx TIKTOKEN_CACHE_DIR "{dst}"')
    print()
    print("검증:")
    print('  python -c "import os,tiktoken; print(tiktoken.get_encoding(\'o200k_base\').encode(\'테스트\'))"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
