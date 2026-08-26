"""
Quick-Print PDF Viewer
- PDF를 열면 현재 쪽이 창 크기에 맞춰(페이지 맞춤) 표시됨 — 이 상태가 줌아웃 최대치
- Ctrl + 마우스 휠로 줌인/줌아웃 (올리면 확대, 내리면 축소, 페이지 맞춤 아래로는 더 축소 안 됨)
- 확대된 상태: 클릭 후 드래그하면 페이지 안을 이동(패닝, 커서가 움켜쥔 손 모양으로 바뀜),
  일반 휠은 페이지 안에서 위아래로 스크롤
- 페이지 맞춤(줌아웃 최대) 상태: 일반 휠을 굴리면 이전/다음 쪽으로 넘어감
- 상단 "쪽 번호" 입력칸에 숫자를 입력하고 그 칸에서 Enter를 누르면 해당 쪽으로 이동 (인쇄되지 않으며, 이동 후 칸은 다시 비워짐)
- 입력칸 밖에서 Enter를 누르면 현재 화면에 보이는 쪽이 확인창 없이 바로 인쇄됨
- 이전/다음 버튼(또는 방향키)으로 쪽 넘기기
- 왼쪽 북마크(목차) 목록은 PDF에 북마크가 있을 때만 나타나며, 클릭하면 해당 쪽으로 이동
  → 이 패널의 경계를 마우스로 드래그해서 넓히면, PDF 문서 폭은 그대로 유지된 채 창 전체 폭이 늘어남
- 파일은 보통 "연결 프로그램"으로 더블클릭해서 열지만, 필요하면 Ctrl+O로도 열 수 있고,
  PDF 파일을 창 위로 끌어다 놓아도(드래그 앤 드롭) 바로 열림

필요 라이브러리 (Windows, cmd/PowerShell에서 설치):
    pip install pymupdf PyQt5

실행:
    python quickprint_pdf_viewer.py

독립 실행 파일(.exe)로 만들고 싶으면:
    pip install pyinstaller
    pyinstaller --onefile --windowed quickprint_pdf_viewer.py
"""

import sys
import os
import pymupdf as fitz  # PyMuPDF (오픈소스, MuPDF 기반)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QFileDialog, QSplitter, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QLineEdit, QShortcut, QScrollBar
)
from PyQt5.QtGui import (
    QImage, QPixmap, QIntValidator, QKeySequence, QColor, QPainter, QPolygon,
    QPen, QLinearGradient, QRadialGradient, QBrush, QPainterPath
)
from PyQt5.QtCore import Qt, QSettings, QTimer, QPoint, QRectF

MIN_ZOOM = 1.0   # 1.0 = 페이지 맞춤 (더 이상 축소 불가)
MAX_ZOOM = 5.0
ZOOM_STEP = 1.15
APP_TITLE = "Quick-Print PDF Viewer"


class PannableLabel(QLabel):
    """페이지 이미지를 표시하고, 확대 상태에서 클릭+드래그로 이동(패닝)하거나, 평범한 클릭은 콜백으로 알리는 라벨"""

    def __init__(self, scroll_area: QScrollArea, on_click=None):
        super().__init__()
        self.scroll_area = scroll_area
        self._on_click = on_click
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: transparent;")  # 이미지 없을 때 흰 조각이 남지 않도록
        self._dragging = False
        self._drag_start = None
        self._h_start = 0
        self._v_start = 0
        self._press_pos = None
        self._moved = False
        self.setCursor(Qt.ArrowCursor)

    def is_scrollable(self) -> bool:
        return (
            self.scroll_area.horizontalScrollBar().maximum() > 0
            or self.scroll_area.verticalScrollBar().maximum() > 0
        )

    def update_cursor(self):
        if not self._dragging:
            self.setCursor(Qt.OpenHandCursor if self.is_scrollable() else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._moved = False
            if self.is_scrollable():
                self._dragging = True
                self._drag_start = event.globalPos()
                self._h_start = self.scroll_area.horizontalScrollBar().value()
                self._v_start = self.scroll_area.verticalScrollBar().value()
                self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and (event.pos() - self._press_pos).manhattanLength() > 4:
            self._moved = True
        if self._dragging:
            delta = event.globalPos() - self._drag_start
            self.scroll_area.horizontalScrollBar().setValue(self._h_start - delta.x())
            self.scroll_area.verticalScrollBar().setValue(self._v_start - delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.update_cursor()
        elif not self._moved and self._on_click and event.button() == Qt.LeftButton:
            # 드래그 없이 단순 클릭 — 여러 페이지가 나열된 상태에서 페이지 선택용
            self._on_click(event.pos().x(), event.pos().y())
        self._press_pos = None
        super().mouseReleaseEvent(event)


class PageScrollArea(QScrollArea):
    """
    페이지를 표시하는 영역.
    - Ctrl+휠 = 줌
    - 확대된 상태에서 일반 휠 = 페이지 안에서 위아래 스크롤 (드래그 패닝도 가능)
    - 페이지 맞춤(줌아웃 최대) 상태에서 일반 휠 = 이전/다음 쪽 넘기기
    """

    def __init__(self, on_wheel_zoom, on_wheel_page, on_page_click=None):
        super().__init__()
        self._on_wheel_zoom = on_wheel_zoom
        self._on_wheel_page = on_wheel_page
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            QScrollArea { background-color: #757575; border: none; }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 130);
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 190);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 8px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: rgba(255, 255, 255, 130);
                border-radius: 4px;
                min-width: 24px;
            }
            QScrollBar::handle:horizontal:hover {
                background: rgba(255, 255, 255, 190);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
        """)

        self.label = PannableLabel(self, on_click=on_page_click)
        self.setWidget(self.label)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            # Ctrl+휠 = 줌
            self._on_wheel_zoom(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
            return

        if self.label.is_scrollable():
            # 확대된 상태 → 페이지 내부 스크롤
            super().wheelEvent(event)
        else:
            # 페이지 맞춤 상태 → 휠로 쪽 넘기기 (위로 = 이전 쪽, 아래로 = 다음 쪽)
            self._on_wheel_page(1 if event.angleDelta().y() > 0 else -1)
            event.accept()

    def set_image(self, qimage: QImage):
        pixmap = QPixmap.fromImage(qimage)
        self.label.setPixmap(pixmap)
        self.label.resize(pixmap.size())
        self.label.update_cursor()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_PageUp, Qt.Key_PageDown):
            # QScrollArea가 기본적으로 이 키를 '자체 스크롤'로 가로채버려서,
            # (특히 다른 창을 오갔다 온 뒤 포커스가 이 영역에 있을 때) 쪽 넘기기가 먹통이 되는 문제 방지.
            # 여기서 소비하지 않고 무시(ignore)해서 상위인 메인 창의 keyPressEvent로 전달되게 한다.
            event.ignore()
            return
        super().keyPressEvent(event)


class BookmarkTree(QTreeWidget):
    """북마크 목록. 휠 이벤트를 이 목록 안에서만 처리하고, 절대 다른 위젯(페이지 뷰어)으로 새어나가지 않도록 한다."""

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()  # 이 위젯이 항상 이벤트를 소비 — 페이지 뷰어의 휠 동작과 완전히 분리


class PageNumberInput(QLineEdit):
    """쪽 번호 입력칸. Enter는 여기서 이동 처리만 하고, 인쇄 단축키로 넘어가지 않도록 이벤트를 확실히 소비한다."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PDFClickPrinter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.doc = None
        self.current_page = 0
        self._row_anchor = 0  # 여러 페이지가 나열될 때 줄의 시작 페이지(클릭 선택과 별개로 유지)
        self._page_regions = []  # 렌더링된 각 페이지의 클릭 판정 영역 [(page_idx, x_start, width), ...]
        self.setAcceptDrops(True)  # 창 위로 PDF 파일을 끌어다 놓으면 열리도록
        self.zoom = MIN_ZOOM

        # 마지막으로 사용한 창 크기/위치 기억 (레지스트리 HKCU\Software\PDFClickPrint 에 저장됨)
        self.settings = QSettings("PDFClickPrint", "PDFClickPrint")

        # 창/스플리터 크기 조절 중 매 순간 다시 그리면 버벅이므로, 조절이 멈춘 뒤 한 번만 렌더링
        self._resize_render_timer = QTimer(self)
        self._resize_render_timer.setSingleShot(True)
        self._resize_render_timer.timeout.connect(self.render_current_page)

        saved_geometry = self.settings.value("window_geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        else:
            self.resize(1000, 750)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # 상단 바 (얇게: 여백/버튼 크기 축소)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(6)

        compact_btn_style = "QPushButton { padding: 2px 8px; }"

        open_btn = QPushButton("PDF 열기")
        open_btn.setStyleSheet(compact_btn_style)
        open_btn.clicked.connect(self.open_pdf)
        top_bar.addWidget(open_btn)

        self.prev_btn = QPushButton("◀ 이전")
        self.prev_btn.setStyleSheet(compact_btn_style)
        self.prev_btn.clicked.connect(self.prev_page)
        top_bar.addWidget(self.prev_btn)

        self.next_btn = QPushButton("다음 ▶")
        self.next_btn.setStyleSheet(compact_btn_style)
        self.next_btn.clicked.connect(self.next_page)
        top_bar.addWidget(self.next_btn)

        top_bar.addWidget(QLabel("쪽 번호:"))
        self.page_input = PageNumberInput()
        self.page_input.setValidator(QIntValidator(1, 999999, self))
        self.page_input.setFixedWidth(60)
        self.page_input.setStyleSheet("padding: 2px;")
        # 이 칸에서 Enter를 누르면 이동만 하고, 인쇄로 이어지지 않도록 이 위젯이 이벤트를 직접 처리
        self.page_input.returnPressed.connect(self.go_to_page_from_input)
        top_bar.addWidget(self.page_input)

        self.status_label = QLabel("PDF를 열어주세요")
        top_bar.addWidget(self.status_label)
        top_bar.addStretch()
        top_bar_widget = QWidget()
        top_bar_widget.setLayout(top_bar)
        top_bar_widget.setMaximumHeight(30)
        main_layout.addWidget(top_bar_widget)

        # 왼쪽: 북마크(목차) 목록 / 오른쪽: 페이지 뷰
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.splitterMoved.connect(self.on_splitter_moved)

        self.bookmark_tree = BookmarkTree()
        self.bookmark_tree.setHeaderHidden(True)
        self.bookmark_tree.itemClicked.connect(self.jump_to_bookmark)
        self.bookmark_tree.hide()
        self.splitter.addWidget(self.bookmark_tree)

        self.page_area = PageScrollArea(self.on_wheel_zoom, self.on_wheel_page, on_page_click=self.on_page_click)

        # 오른쪽: 페이지 뷰 + 문서 전체 진행 표시줄(항상 보임, 드래그하면 해당 쪽으로 이동)
        page_container = QWidget()
        page_container_layout = QHBoxLayout(page_container)
        page_container_layout.setContentsMargins(0, 0, 0, 0)
        page_container_layout.setSpacing(0)
        page_container_layout.addWidget(self.page_area, stretch=1)

        self.page_progress_bar = QScrollBar(Qt.Vertical)
        self.page_progress_bar.setFixedWidth(10)
        self.page_progress_bar.setStyleSheet("""
            QScrollBar:vertical {
                background: #45494e;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 130);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 190);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        self.page_progress_bar.setRange(0, 0)
        self.page_progress_bar.setEnabled(False)
        self.page_progress_bar.valueChanged.connect(self.on_progress_bar_changed)
        page_container_layout.addWidget(self.page_progress_bar)

        self.splitter.addWidget(page_container)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([0, 1000])
        main_layout.addWidget(self.splitter, stretch=1)

        # 북마크 패널을 드래그로 넓힐 때, PDF 뷰 폭은 고정하고 대신 창 전체를 넓히기 위한 상태값
        self._adjusting_splitter = False
        self._fixed_page_width = self.splitter.sizes()[1]

        self.setCentralWidget(central)
        self.set_nav_enabled(False)

        # Ctrl+O로도 파일을 열 수 있음
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_pdf)

        # "연결 프로그램"으로 실행되어 PDF 경로가 인자로 넘어온 경우 자동으로 열기.
        # 창이 실제로 화면에 표시되어 레이아웃이 확정된 뒤에 로드해야
        # 뷰 영역 크기를 정확히 계산해서 처음부터 페이지 맞춤으로 표시된다.
        if len(sys.argv) > 1:
            path = sys.argv[1]
            QTimer.singleShot(0, lambda: self.load_pdf(path))

    # ---------- 북마크 패널 폭 조절 시 창 전체 폭을 같이 조절 ----------
    def on_splitter_moved(self, pos, index):
        if self._adjusting_splitter:
            return
        sizes = self.splitter.sizes()
        bookmark_width, page_width = sizes[0], sizes[1]
        delta = page_width - self._fixed_page_width
        if delta == 0:
            return
        self._adjusting_splitter = True
        self.resize(self.width() - delta, self.height())
        self.splitter.setSizes([bookmark_width, self._fixed_page_width])
        self._adjusting_splitter = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._adjusting_splitter and self.splitter.sizes()[1] > 0:
            # 사용자가 창 자체를 직접 리사이즈한 경우엔 PDF 뷰 폭 기준값을 갱신
            self._fixed_page_width = self.splitter.sizes()[1]
        if self.doc:
            # 크기 조절이 계속되는 동안은 다시 그리지 않고, 120ms간 조용하면 그때 한 번만 그림
            self._resize_render_timer.start(120)

    # ---------- 줌 ----------
    def on_wheel_zoom(self, direction: int):
        if not self.doc:
            return
        if direction > 0:
            self.zoom = min(MAX_ZOOM, self.zoom * ZOOM_STEP)
        else:
            self.zoom = max(MIN_ZOOM, self.zoom / ZOOM_STEP)
        self.render_current_page()

    def on_wheel_page(self, direction: int):
        # 페이지 맞춤 상태에서 휠을 굴렸을 때: 위로 굴리면 이전 쪽, 아래로 굴리면 다음 쪽
        if direction > 0:
            self.prev_page()
        else:
            self.next_page()

    # ---------- 파일 열기 / 북마크 ----------
    def set_nav_enabled(self, enabled: bool):
        self.prev_btn.setEnabled(enabled)
        self.next_btn.setEnabled(enabled)

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF 파일 선택", "", "PDF Files (*.pdf)")
        if not path:
            return
        self.load_pdf(path)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and any(u.toLocalFile().lower().endswith(".pdf") for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        for url in urls:
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.load_pdf(path)
                break
        event.acceptProposedAction()

    def load_pdf(self, path: str):
        self.doc = fitz.open(path)
        self.current_page = 0
        self._row_anchor = 0
        self.zoom = MIN_ZOOM
        self.set_nav_enabled(True)
        self.setWindowTitle(f"{os.path.basename(path)} — {APP_TITLE}")
        self.load_bookmarks()
        # 북마크 패널이 새로 나타나거나 사라지면서 스플리터 레이아웃이 바뀔 수 있으므로,
        # 그 레이아웃이 확정된 뒤에 렌더링해야 뷰 폭을 정확히 계산해 스크롤이 생기지 않는다.
        QTimer.singleShot(0, self.render_current_page)

    def load_bookmarks(self):
        self.bookmark_tree.clear()
        toc = self.doc.get_toc()  # [[level, title, page_number], ...] (page_number는 1부터 시작)
        if not toc:
            self.bookmark_tree.hide()
            return

        stack = []  # (level, QTreeWidgetItem)
        for level, title, page_number in toc:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, page_number)
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.bookmark_tree.addTopLevelItem(item)
            stack.append((level, item))
        self.bookmark_tree.expandAll()
        self.bookmark_tree.show()
        if self.splitter.sizes()[0] == 0:
            self.splitter.setSizes([220, self._fixed_page_width])

    def jump_to_bookmark(self, item, column):
        page_number = item.data(0, Qt.UserRole)
        if page_number is None or not self.doc:
            return
        target = max(0, min(page_number - 1, len(self.doc) - 1))
        self.current_page = target
        self._row_anchor = target
        self.zoom = MIN_ZOOM
        self.render_current_page()

    def go_to_page_from_input(self):
        if not self.doc:
            return
        text = self.page_input.text().strip()
        if not text:
            return
        target = max(1, min(int(text), len(self.doc))) - 1
        self.current_page = target
        self._row_anchor = target
        self.zoom = MIN_ZOOM
        self.render_current_page()
        self.page_input.clear()

    # ---------- 렌더링 ----------
    def render_current_page(self):
        if not self.doc:
            return

        viewport_size = self.page_area.viewport().size()
        vw, vh = viewport_size.width(), viewport_size.height()
        if vw <= 0 or vh <= 0:
            return

        self._page_regions = []
        target_page = self.doc[self.current_page]
        page_w_pt, page_h_pt = target_page.rect.width, target_page.rect.height
        if page_w_pt <= 0 or page_h_pt <= 0:
            return

        if self.zoom > MIN_ZOOM:
            # 확대 상태: 선택된(현재) 페이지 한 장만, 폭/높이 둘 다 맞춰서 렌더링
            fit_scale = min(vw / page_w_pt, vh / page_h_pt)
            final_scale = max(fit_scale, 0.01) * self.zoom
            pix = target_page.get_pixmap(matrix=fitz.Matrix(final_scale, final_scale))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        else:
            # 페이지 맞춤(최대 축소) 상태: _row_anchor부터 세로 높이에 맞춰 옆으로 몇 장이나
            # 들어가는지 계산해서 이어 붙인다. 창이 좁으면 자연히 한 장만 표시된다.
            anchor_page = self.doc[self._row_anchor]
            anchor_w_pt, anchor_h_pt = anchor_page.rect.width, anchor_page.rect.height

            # 페이지들을 담을 실제 여백(margin)을 미리 확보해서, 합성 이미지가 뷰 영역을
            # 절대 넘지 않도록 한다 — 넘치면 스크롤 가능 상태로 오인되어 휠/클릭 동작이 꼬인다.
            margin = 9
            avail_h = max(vh - margin * 2, 10)
            avail_w = max(vw - margin * 2, 10)
            scale = avail_h / max(anchor_h_pt, 0.01)
            disp_w_at_scale = anchor_w_pt * scale

            if disp_w_at_scale > avail_w:
                # 한 장조차 폭에 안 맞는 경우(좁은 창/세로로 긴 페이지) → 기존처럼 한 장만, 폭/높이 둘 다 맞춤
                self._row_anchor = self.current_page
                fit_scale = min(vw / page_w_pt, vh / page_h_pt)
                pix = target_page.get_pixmap(matrix=fitz.Matrix(fit_scale, fit_scale))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                self._page_regions = [(self.current_page, 0, img.width())]
            else:
                gap = 10
                shown = []  # (page_idx, QImage, disp_w)
                total_w = 0
                idx = self._row_anchor
                while idx < len(self.doc) and len(shown) < 12:
                    p = self.doc[idx]
                    pw_pt, ph_pt = p.rect.width, p.rect.height
                    if pw_pt <= 0 or ph_pt <= 0:
                        break
                    disp_w = pw_pt * scale
                    needed_total = total_w + disp_w + (gap if shown else 0)
                    if shown and needed_total > avail_w:
                        break
                    pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale))
                    pimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                    shown.append((idx, pimg, pimg.width()))
                    total_w = needed_total
                    idx += 1

                shown_ids = [i for i, _, _ in shown]
                if self.current_page not in shown_ids:
                    # 선택된 페이지가 화면에서 벗어났으면(리사이즈 등) 줄의 시작 페이지로 선택을 되돌림
                    self.current_page = self._row_anchor

                if len(shown) <= 1:
                    only_idx, only_img, only_w = shown[0]
                    img = only_img
                    self._page_regions = [(only_idx, 0, only_w)]
                else:
                    border_width = 6
                    border_radius = 10
                    accent = QColor("#5C8AE0")  # 로고와 같은 계열의 파란색

                    total_content_w = sum(w for _, _, w in shown) + gap * (len(shown) - 1)
                    start_x = margin + max(0, (avail_w - total_content_w) // 2)

                    # 캔버스를 뷰 영역 크기에 정확히 맞춤(vw x vh) — 절대 넘치지 않게
                    composite = QImage(vw, vh, QImage.Format_RGB888)
                    composite.fill(QColor("#757575"))
                    painter = QPainter(composite)
                    painter.setRenderHint(QPainter.Antialiasing)

                    x = start_x
                    for page_idx, im, w in shown:
                        painter.drawImage(x, margin, im)
                        self._page_regions.append((page_idx, x, w))
                        x += w + gap

                    # 선택된 페이지: 두툼한 파란색 둥근 테두리
                    x = start_x
                    for page_idx, im, w in shown:
                        if page_idx == self.current_page:
                            pen = QPen(accent, border_width)
                            pen.setJoinStyle(Qt.RoundJoin)
                            painter.setPen(pen)
                            painter.setBrush(Qt.NoBrush)
                            rect = QRectF(
                                x - border_width / 2 - 1,
                                margin - border_width / 2 - 1,
                                w + border_width + 2,
                                im.height() + border_width + 2,
                            )
                            painter.drawRoundedRect(rect, border_radius, border_radius)
                        x += w + gap

                    painter.end()
                    img = composite

        if img is None:
            return
        self.page_area.set_image(img)

        zoom_pct = round(self.zoom * 100)
        self.status_label.setText(
            f"{self.current_page + 1} / {len(self.doc)}쪽 · {zoom_pct}% — Enter를 누르면 현재 페이지가 인쇄됩니다"
        )
        self._sync_progress_bar()

    def _sync_progress_bar(self):
        """오른쪽 진행 표시줄을 현재 문서/쪽 상태와 맞춘다 (프로그램에 의한 갱신이라 신호는 잠시 막음)."""
        self.page_progress_bar.blockSignals(True)
        if not self.doc or len(self.doc) <= 1:
            self.page_progress_bar.setRange(0, 0)
            self.page_progress_bar.setEnabled(False)
        else:
            self.page_progress_bar.setRange(1, len(self.doc))
            self.page_progress_bar.setPageStep(1)
            self.page_progress_bar.setValue(self.current_page + 1)
            self.page_progress_bar.setEnabled(True)
        self.page_progress_bar.blockSignals(False)

    def on_progress_bar_changed(self, value: int):
        # 사용자가 오른쪽 진행 표시줄을 드래그/클릭했을 때 — 해당 쪽으로 바로 이동
        if not self.doc:
            return
        target = value - 1
        if target == self.current_page:
            return
        self.current_page = target
        self._row_anchor = target
        self.zoom = MIN_ZOOM
        self.render_current_page()

    def on_page_click(self, x: int, y: int):
        # 여러 페이지가 나열된 상태에서 클릭한 위치가 어느 페이지인지 찾아 선택(=현재 페이지)을 바꾼다.
        if len(self._page_regions) <= 1:
            return
        for page_idx, x_start, width in self._page_regions:
            if x_start <= x <= x_start + width:
                if page_idx != self.current_page:
                    self.current_page = page_idx
                    self.render_current_page()
                return

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self._row_anchor = self.current_page
            self.zoom = MIN_ZOOM
            self.render_current_page()

    def next_page(self):
        if self.doc and self.current_page < len(self.doc) - 1:
            self.current_page += 1
            self._row_anchor = self.current_page
            self.zoom = MIN_ZOOM
            self.render_current_page()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.prev_page()
        elif event.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self.next_page()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.print_current_page()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.settings.setValue("window_geometry", self.saveGeometry())
        super().closeEvent(event)

    def print_current_page(self):
        if not self.doc:
            return
        if self.page_input.hasFocus():
            # 쪽 번호 입력칸에서의 Enter는 이동 전용 — 만약을 위한 이중 안전장치
            return

        from PyQt5.QtGui import QPainter
        from PyQt5.QtPrintSupport import QPrinter

        # 기본 프린터로 바로 인쇄 (프린터 선택창 없음, 화면 줌 배율과 무관하게 항상 고해상도로 인쇄)
        printer = QPrinter(QPrinter.HighResolution)
        # 특정 프린터를 고정하고 싶으면 아래 줄의 주석을 풀고 이름을 지정하세요.
        # printer.setPrinterName("프린터이름")

        page = self.doc[self.current_page]
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))  # 인쇄 품질용 고해상도 렌더링
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)

        painter = QPainter(printer)
        rect = painter.viewport()
        scaled_size = img.size()
        scaled_size.scale(rect.size(), Qt.KeepAspectRatio)
        painter.setViewport(rect.x(), rect.y(), scaled_size.width(), scaled_size.height())
        painter.setWindow(img.rect())
        painter.drawImage(0, 0, img)
        painter.end()

        self.status_label.setText(f"{self.current_page + 1}쪽 인쇄 완료")


def _rounded_rect_path(x, y, w, h, r):
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _rounded_page_path(x, y, w, h, fold, radius):
    path = QPainterPath()
    path.moveTo(x + radius, y)
    path.lineTo(x + w - fold, y)
    path.lineTo(x + w, y + fold)
    path.lineTo(x + w, y + h - radius)
    path.quadTo(x + w, y + h, x + w - radius, y + h)
    path.lineTo(x + radius, y + h)
    path.quadTo(x, y + h, x, y + h - radius)
    path.lineTo(x, y + radius)
    path.quadTo(x, y, x + radius, y)
    path.closeSubpath()
    return path


def _directional_shadow(painter, path_fn, x, y, w, h, layers, max_grow, base_alpha):
    """그림자를 오른쪽(3시)·아래쪽(6시) 방향으로만 번지게 한다. 좌상단 위치는 그대로 두고
    폭/높이만 늘려서 오른쪽·아래쪽 가장자리만 확장하므로, 위·왼쪽에는 그림자가 생기지 않는다."""
    for i in range(layers, 0, -1):
        t = i / layers
        grow = max_grow * t
        alpha = int(base_alpha * (1 - t)) + 3
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, alpha))
        painter.drawPath(path_fn(x, y, w + grow, h + grow))


def _draw_logo_page(painter, x, y, w, h, fold, radius, top_color, bottom_color, fold_color):
    grad = QLinearGradient(x, y, x, y + h)
    grad.setColorAt(0, QColor(top_color))
    grad.setColorAt(1, QColor(bottom_color))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawPath(_rounded_page_path(x, y, w, h, fold, radius))

    painter.setBrush(QColor(fold_color))
    painter.drawPolygon(QPolygon([
        QPoint(int(x + w - fold), int(y)),
        QPoint(int(x + w), int(y + fold)),
        QPoint(int(x + w - fold), int(y + fold)),
    ]))

    # 상단 은은한 광택
    hl = QLinearGradient(x, y, x, y + h * 0.35)
    hl.setColorAt(0, QColor(255, 255, 255, 90))
    hl.setColorAt(1, QColor(255, 255, 255, 0))
    painter.setBrush(QBrush(hl))
    painter.setClipPath(_rounded_page_path(x, y, w, h, fold, radius))
    painter.drawRect(int(x), int(y), int(w), int(h * 0.4))
    painter.setClipping(False)


def _logo_content_lines(painter, x, y, w, color, ratios, gap=20, h=8):
    painter.setBrush(QColor(color))
    for i, r in enumerate(ratios):
        painter.drawRoundedRect(int(x), int(y + i * gap), int(w * r), h, h // 2, h // 2)


def build_splash_pixmap() -> QPixmap:
    """
    겹쳐진 두 장의 문서를 담은, 화면 위에 떠 있는 듯한 카드 로고.
    카드 바깥쪽 배경은 완전히 투명 — 프로그램 창(SplashCard)이 반투명 배경으로 띄워야
    실제로 바탕화면 위에 뜬 것처럼 보인다(build_splash_pixmap 단독으로는 그냥 알파 채널이 있는
    이미지일 뿐). 그림자는 오른쪽·아래쪽으로만 번지도록 해서 입체감을 준다.
    텍스트는 전혀 쓰지 않으므로 폰트 엔진(첫 텍스트 렌더링 지연)과 무관하게 항상 즉시 그려진다.
    """
    card_w, card_h = 360, 220
    margin = 40  # 카드 바깥 그림자가 번질 여유 공간(투명)
    width, height = card_w + margin * 2, card_h + margin * 2

    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    card_x, card_y = margin, margin
    card_r = 22

    def card_path_fn(x, y, w, h):
        return _rounded_rect_path(x, y, w, h, card_r)

    # 카드 전체 그림자 (오른쪽·아래쪽으로만)
    _directional_shadow(painter, card_path_fn, card_x, card_y, card_w, card_h,
                         layers=10, max_grow=22, base_alpha=13)

    # 카드 배경(방사형 그라디언트, 둥근 모서리)
    rg = QRadialGradient(card_x + card_w / 2, card_y + card_h * 0.42, card_w * 0.8)
    rg.setColorAt(0, QColor("#3D63A8"))
    rg.setColorAt(1, QColor("#254A85"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(rg))
    painter.drawPath(card_path_fn(card_x, card_y, card_w, card_h))

    # 카드 안 문서 두 장 (각각 자체 그림자, 오른쪽·아래쪽으로만)
    page_w, page_h = 118, 156
    cx, cy = card_x + card_w // 2, card_y + card_h // 2
    fold = 26
    radius = 10

    back_x, back_y = cx - page_w // 2 + 20, cy - page_h // 2 - 14
    front_x, front_y = cx - page_w // 2 - 14, cy - page_h // 2 + 14

    def page_path_fn(x, y, w, h):
        return _rounded_page_path(x, y, w, h, fold, radius)

    _directional_shadow(painter, page_path_fn, back_x, back_y, page_w, page_h,
                         layers=5, max_grow=10, base_alpha=10)
    _draw_logo_page(painter, back_x, back_y, page_w, page_h, fold, radius, "#E7ECF7", "#C9D6EE", "#AEC0E8")

    _directional_shadow(painter, page_path_fn, front_x, front_y, page_w, page_h,
                         layers=7, max_grow=14, base_alpha=14)
    _draw_logo_page(painter, front_x, front_y, page_w, page_h, fold, radius, "#FFFFFF", "#EDF1FA", "#D3DEF2")

    _logo_content_lines(painter, front_x + 18, front_y + 32, page_w - 36, "#8B9CC2", [1.0, 0.7, 1.0], gap=20, h=8)

    painter.end()
    return pix


class SplashCard(QWidget):
    """
    투명 배경의 프레임 없는 창에 로고 카드를 그려서, 실제 바탕화면 위에 카드가
    떠 있는 것처럼 보이게 하는 스플래시. QSplashScreen은 불투명 배경이라 이 효과를 못 내서
    QWidget을 직접 반투명 창으로 구성했다.
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pixmap = build_splash_pixmap()
        self.setFixedSize(self._pixmap.size())
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)


def main():
    app = QApplication(sys.argv)

    # 첫 텍스트 렌더링이 이 PC에서 유독 느려서(보안 프로그램의 폰트 파일 검사로 추정),
    # 텍스트 없는 로고 카드를 먼저 즉시 띄워 체감 지연을 줄인다.
    splash = SplashCard()
    splash.show()
    app.processEvents()  # 스플래시가 실제로 화면에 그려지도록 강제

    win = PDFClickPrinter()
    win.show()
    splash.close()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
