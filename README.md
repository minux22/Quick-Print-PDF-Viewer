# QuickPrint PDF Viewer

가볍게 PDF 내용을 확인하고, Enter 한 번으로 현재 페이지(만)를 바로 인쇄할 수 있는 Windows용 프로그램입니다.
업무상 필요로, Claude를 통해 작성했습니다.

## 주요 기능

- 페이지 맞춤 뷰 / Ctrl+휠 확대·축소 / 확대 시 드래그로 이동(패닝)
- 창 폭을 넓히면 여러 페이지가 옆으로 나열되어 표시되고, 클릭으로 원하는 페이지를 선택 가능
- Enter 키로 현재 선택된 페이지만 확인창 없이 바로 인쇄
- 북마크(목차)가 있는 PDF는 좌측에 목록 표시, 클릭 시 해당 쪽으로 이동
- 상단 "쪽 번호" 입력창으로 특정 쪽 바로 이동
- PDF 파일을 창 위로 드래그 앤 드롭해서 열기
- 마지막 창 크기/위치 자동 기억

## 실행 방법 (Windows)

```bash
pip install pymupdf PyQt5
python quickprint_pdf_viewer.py
```

## 실행 파일(.exe)로 빌드

```bash
pip install pyinstaller

# 빠른 실행 속도 우선 (폴더 형태로 생성)
python -m PyInstaller --onedir --windowed --noupx quickprint_pdf_viewer.py

# 단일 파일로 배포하고 싶을 때
python -m PyInstaller --onefile --windowed --noupx quickprint_pdf_viewer.py
```

## 사용한 오픈소스

| 라이브러리 | 용도 | 출처 | 라이선스 |
|---|---|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (fitz) | PDF 렌더링 (MuPDF 엔진) | Artifex Software | AGPL-3.0 (또는 상업용) |
| [PyQt5](https://www.riverbankcomputing.com/software/pyqt/) | 화면 UI, 인쇄 | Riverbank Computing | GPL-3.0 (또는 상업용) |

두 라이브러리 모두 카피레프트 라이선스(무료로 쓰는 대신, 이 코드를 이용해 만든 프로그램도 소스를 공개해야 함)라서, 이 저장소도 아래와 같이 **GPL-3.0**으로 공개합니다.

## 라이선스

[GPL-3.0](LICENSE)
