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
    QScrollArea, QLineEdit, QShortcut, QScrollBar, QButtonGroup
)
from PyQt5.QtGui import (
    QImage, QPixmap, QIntValidator, QKeySequence, QColor, QPainter, QPolygon,
    QPen, QLinearGradient, QRadialGradient, QBrush, QPainterPath
)
from PyQt5.QtCore import Qt, QSettings, QTimer, QPoint, QRectF, QRect

MIN_ZOOM = 1.0   # 1.0 = 페이지 맞춤 (더 이상 축소 불가)
MAX_ZOOM = 5.0
ZOOM_STEP = 1.15
APP_TITLE = "Quick-Print PDF Viewer"
MIN_PAGE_DISPLAY_WIDTH = 260  # Wide 모드에서 이 폭 밑으로는 페이지를 줄이지 않음(가독성 하한선)
MAX_PAGES_IN_ROW_WIDE = 6      # Wide 모드: 화면이 아무리 넓어도 한 줄에 최대 이 장수까지만


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
        self.view_mode = "single"  # "single"(한 장) / "two"(두 쪽 스프레드) / "wide"(듀얼모니터 활용, 최대 6장)
        self._pre_wide_mode = "single"  # Wide로 전환하기 직전의 모드 (ESC로 돌아갈 곳)
        self._pre_wide_geometry = None  # Wide로 전환하기 전의 창 크기/위치
        self._bookmark_saved_width = 220  # 북마크 패널을 껐다가 다시 켤 때 복원할 폭
        self._mode_geometry = {"single": None, "two": None}  # 모드별로 마지막 창 크기/위치 기억
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

        mode_btn_style = """
            QPushButton { padding: 2px 10px; font-weight: bold; }
            QPushButton:checked {
                background-color: #2F5496;
                color: white;
                border: 1px solid #2F5496;
            }
        """
        self.single_mode_btn = QPushButton("Single")
        self.single_mode_btn.setCheckable(True)
        self.single_mode_btn.setChecked(True)
        self.single_mode_btn.setStyleSheet(mode_btn_style)
        self.single_mode_btn.clicked.connect(lambda: self.set_view_mode("single"))
        top_bar.addWidget(self.single_mode_btn)

        self.two_mode_btn = QPushButton("Two")
        self.two_mode_btn.setCheckable(True)
        self.two_mode_btn.setStyleSheet(mode_btn_style)
        self.two_mode_btn.clicked.connect(lambda: self.set_view_mode("two"))
        top_bar.addWidget(self.two_mode_btn)

        self.wide_mode_btn = QPushButton("Wide")
        self.wide_mode_btn.setCheckable(True)
        self.wide_mode_btn.setStyleSheet(mode_btn_style)
        self.wide_mode_btn.clicked.connect(lambda: self.set_view_mode("wide"))
        top_bar.addWidget(self.wide_mode_btn)

        self.mode_btn_group = QButtonGroup(self)
        self.mode_btn_group.setExclusive(True)
        self.mode_btn_group.addButton(self.single_mode_btn)
        self.mode_btn_group.addButton(self.two_mode_btn)
        self.mode_btn_group.addButton(self.wide_mode_btn)

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
        self.page_container = QWidget()
        page_container_layout = QHBoxLayout(self.page_container)
        page_container_layout.setContentsMargins(0, 0, 0, 0)
        page_container_layout.setSpacing(0)
        page_container_layout.addWidget(self.page_area, stretch=1)

        # 북마크 패널 on/off 화살표 — page_container 왼쪽 가장자리에 떠 있는 작은 버튼
        # (레이아웃에 넣지 않고 자유롭게 위치시켜서, 페이지 영역을 살짝 침범해도 무방하게 둔다)
        self.bookmark_toggle_btn = QPushButton("‹", self.page_container)
        self.bookmark_toggle_btn.setFixedSize(14, 44)
        self.bookmark_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.bookmark_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 90);
                color: white;
                border: none;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(0, 0, 0, 150); }
        """)
        self.bookmark_toggle_btn.clicked.connect(self.toggle_bookmark_panel)
        self.bookmark_toggle_btn.hide()  # 문서를 열기 전까지는 숨김

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

        self.splitter.addWidget(self.page_container)

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
        self._position_bookmark_toggle()
        if self.doc:
            # 크기 조절이 계속되는 동안은 다시 그리지 않고, 120ms간 조용하면 그때 한 번만 그림
            self._resize_render_timer.start(120)

    def _position_bookmark_toggle(self):
        btn = self.bookmark_toggle_btn
        y = max(0, (self.page_container.height() - btn.height()) // 2)
        btn.move(0, y)
        btn.raise_()

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
        # 페이지 맞춤 상태에서 휠을 굴렸을 때: 위로 굴리면 이전, 아래로 굴리면 다음.
        # 여러 페이지가 한 번에 나열되어 있으면, 겹치지 않도록 그 장수만큼 건너뛴다.
        step = len(self._page_regions) if len(self._page_regions) > 1 else 1
        if direction > 0:
            self.jump_by(-step)
        else:
            self.jump_by(step)

    def jump_by(self, delta: int):
        if not self.doc:
            return
        self._navigate_to(self.current_page + delta)

    def _two_mode_spread_start(self, idx: int) -> int:
        """Two 모드에서 idx가 속한 스프레드의 시작 페이지(0-index)를 계산.
        1쪽(idx=0)은 혼자 오른쪽에, 이후 (2,3),(4,5)... 짝수-홀수 순으로 묶여
        홀수 쪽(1-index)이 항상 오른쪽에 오도록 한다."""
        if idx <= 0:
            return 0
        return 1 + ((idx - 1) // 2) * 2

    def _navigate_to(self, target: int):
        if not self.doc:
            return
        target = max(0, min(target, len(self.doc) - 1))
        if self.view_mode == "two":
            self._row_anchor = self._two_mode_spread_start(target)
            self.current_page = target  # 스프레드는 시작 기준으로, 선택은 실제 요청한 페이지로
        else:
            self.current_page = target
            self._row_anchor = target
        self.zoom = MIN_ZOOM
        self.render_current_page()

    def set_view_mode(self, mode: str):
        if mode == self.view_mode:
            return
        old_mode = self.view_mode

        # Single/Two를 떠날 때는 그 시점의 창 크기/위치를 그 모드의 '기억값'으로 저장해둔다
        # (사용자가 그 모드에서 직접 리사이즈했다면, 그 마지막 값이 저장됨)
        if old_mode in ("single", "two"):
            self._mode_geometry[old_mode] = QRect(self.geometry())

        if mode == "wide":
            # Wide로 전환하기 직전 모드/창 크기를 기억해뒀다가, 나중에 돌아올 때 복원 (ESC 포함)
            self._pre_wide_mode = old_mode
            self._pre_wide_geometry = self.saveGeometry()
            self.view_mode = mode
            self._resize_to_span_monitors()
        else:
            self.view_mode = mode
            if old_mode == "wide" and mode == self._pre_wide_mode and self._pre_wide_geometry is not None:
                # Wide 진입 직전과 '같은' 모드로 돌아가는 경우에만 그 상태를 그대로 복원
                self.restoreGeometry(self._pre_wide_geometry)
                self._pre_wide_geometry = None
                self._mode_geometry[mode] = QRect(self.geometry())
            else:
                if old_mode == "wide":
                    # Wide에서 왔지만 진입 직전과 다른 모드로 바로 전환한 경우:
                    # 저장해둔 pre-wide 상태는 이제 의미가 없으니 정리하고, 그 모드 고유의 기억값을 쓴다
                    self._pre_wide_geometry = None
                if self._mode_geometry.get(mode) is not None:
                    # Single↔Two 직접 전환: 그 모드에서 마지막으로 쓰던 크기/위치를 복원
                    self.setGeometry(self._mode_geometry[mode])
                elif mode == "two":
                    # Two를 한 번도 쓴 적 없으면: Single 폭의 2배로 기본값 계산
                    self._apply_default_two_geometry()

        # 버튼 체크 상태를 실제 모드와 맞춤 (ESC 등 버튼 클릭이 아닌 경로로 전환된 경우 대비)
        {"single": self.single_mode_btn, "two": self.two_mode_btn, "wide": self.wide_mode_btn}[mode].setChecked(True)

        self._row_anchor = self.current_page
        self.zoom = MIN_ZOOM
        if self.doc:
            # 특히 Wide 전환 시 창을 두 모니터에 걸치도록 리사이즈하는데, 그 처리가 완전히
            # 끝나기 전에 바로 그리면 아직 옛 크기 기준이라 모니터2쪽이 비어 보일 수 있다.
            # 다음 이벤트 루프로 미뤄서 리사이즈가 확정된 뒤에 그리도록 하고,
            # Wide는 창 관리자 협상이 더 걸릴 수 있어 안전하게 한 번 더 재확인한다.
            QTimer.singleShot(0, self.render_current_page)
            if mode == "wide":
                QTimer.singleShot(120, self.render_current_page)

    def _apply_default_two_geometry(self):
        """Two 모드를 아직 한 번도 안 써서 기억된 크기가 없을 때: Single 폭의 2배로 확장.
        기본은 오른쪽으로 늘리되, 그러면 모니터 오른쪽 경계를 넘는 경우엔 왼쪽으로 확장한다."""
        base = self._mode_geometry.get("single") or self.geometry()
        new_width = base.width() * 2

        screen = self.screen() if hasattr(self, "screen") else None
        screen = screen or QApplication.primaryScreen()
        new_x = base.x()
        if screen is not None:
            avail = screen.availableGeometry()
            right_edge = avail.x() + avail.width()
            if new_x + new_width > right_edge:
                new_x = max(avail.x(), right_edge - new_width)

        new_rect = QRect(new_x, base.y(), new_width, base.height())
        self.setGeometry(new_rect)
        self._mode_geometry["two"] = QRect(new_rect)

    def _resize_to_span_monitors(self):
        screens = QApplication.screens()
        if len(screens) < 2:
            return  # 모니터가 하나뿐이면 굳이 손대지 않음
        combined = QRect()
        for s in screens:
            combined = combined.united(s.geometry())
        self.setGeometry(combined)

    def _get_monitor_seams_in_viewport(self):
        """페이지 뷰 영역(page_area 뷰포트) 좌표계 기준으로, 모니터와 모니터 사이 경계가 되는
        x좌표 목록을 반환한다. Wide 모드에서 페이지가 이 경계에 걸쳐 잘려 보이는 걸 막기 위함."""
        screens = QApplication.screens()
        if len(screens) < 2:
            return []
        origin_x = self.page_area.viewport().mapToGlobal(QPoint(0, 0)).x()
        sorted_screens = sorted(screens, key=lambda s: s.geometry().x())
        seams = []
        for s in sorted_screens[1:]:
            seam_x = s.geometry().x() - origin_x
            if seam_x > 0:
                seams.append(seam_x)
        return seams

    def toggle_bookmark_panel(self):
        if self.bookmark_tree.isVisible():
            current_width = self.splitter.sizes()[0]
            if current_width > 0:
                self._bookmark_saved_width = current_width
            self.bookmark_tree.hide()
            total = sum(self.splitter.sizes())
            self.splitter.setSizes([0, total])
            self._fixed_page_width = total
            self.bookmark_toggle_btn.setText("›")
        else:
            self.bookmark_tree.show()
            total = sum(self.splitter.sizes())
            bw = min(self._bookmark_saved_width, max(total - 100, 0))
            self.splitter.setSizes([bw, total - bw])
            self._fixed_page_width = total - bw
            self.bookmark_toggle_btn.setText("‹")
        self._position_bookmark_toggle()
        if self.doc:
            QTimer.singleShot(0, self.render_current_page)

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
        self.load_bookmarks()  # 북마크 유무에 따라 토글 버튼 표시 여부까지 여기서 결정됨
        self._position_bookmark_toggle()
        # 북마크 패널이 새로 나타나거나 사라지면서 스플리터 레이아웃이 바뀔 수 있으므로,
        # 그 레이아웃이 확정된 뒤에 렌더링해야 뷰 폭을 정확히 계산해 스크롤이 생기지 않는다.
        QTimer.singleShot(0, self.render_current_page)

    def load_bookmarks(self):
        self.bookmark_tree.clear()
        toc = self.doc.get_toc()  # [[level, title, page_number], ...] (page_number는 1부터 시작)
        if not toc:
            self.bookmark_tree.hide()
            self.bookmark_toggle_btn.hide()  # 북마크 정보가 아예 없으면 스위치 자체를 숨김
            # 다음 번 다른(북마크 있는) 문서를 열 때를 위해 splitter도 접어둔 상태로 정리
            if self.splitter.sizes()[0] != 0:
                total = sum(self.splitter.sizes())
                self.splitter.setSizes([0, total])
                self._fixed_page_width = total
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
        self.bookmark_toggle_btn.show()
        self.bookmark_toggle_btn.setText("‹")
        if self.splitter.sizes()[0] == 0:
            self.splitter.setSizes([220, self._fixed_page_width])

    def jump_to_bookmark(self, item, column):
        page_number = item.data(0, Qt.UserRole)
        if page_number is None:
            return
        self._navigate_to(page_number - 1)

    def go_to_page_from_input(self):
        if not self.doc:
            return
        text = self.page_input.text().strip()
        if not text:
            return
        self._navigate_to(int(text) - 1)
        self.page_input.clear()

    # ---------- 렌더링 ----------
    def _composite_row(self, slots, vw, vh, margin, gap, left_align, seams=None):
        """slots: [(page_idx_or_None, QImage_or_None, w, h), ...] 를 한 줄로 이어 그린 합성 이미지와
        클릭 판정 영역 목록을 반환. page_idx가 None인 슬롯은 빈 칸(Two 모드의 1쪽 왼쪽 공백)으로,
        이미지도 클릭 영역도 만들지 않는다.
        seams가 주어지면(Wide 모드 + 듀얼모니터), 어떤 페이지가 모니터 경계에 걸쳐 잘려 보일 것 같으면
        그 페이지를 통째로 다음 모니터 시작 위치로 밀어서 배치한다 — 걸치는 페이지 없음을 보장."""
        avail_w = max(vw - margin * 2, 10)
        total_content_w = sum(w for _, _, w, _ in slots) + gap * (len(slots) - 1)

        if left_align:
            start_x = margin
        else:
            start_x = margin + max(0, (avail_w - total_content_w) // 2)

        composite = QImage(vw, vh, QImage.Format_RGB888)
        composite.fill(QColor("#757575"))
        painter = QPainter(composite)
        painter.setRenderHint(QPainter.Antialiasing)

        regions = []
        drawn = []  # (page_idx, im, w, h, x) — 실제로 그려진 것만
        x = start_x
        for page_idx, im, w, h in slots:
            if seams:
                for seam in seams:
                    if x < seam < x + w:
                        x = seam  # 경계에 걸치지 않도록 다음 모니터 시작 위치로 통째로 밀기
                        break
            if x + w > vw - margin:
                break  # 남은 공간에 안 들어가면 이후 페이지는 그리지 않음
            if im is not None:
                painter.drawImage(x, margin, im)
                regions.append((page_idx, x, w))
            drawn.append((page_idx, im, w, h, x))
            x += w + gap

        # 선택된(현재) 페이지: 두툼한 파란색 둥근 테두리
        border_width = 6
        border_radius = 10
        accent = QColor("#5C8AE0")  # 로고와 같은 계열의 파란색
        for page_idx, im, w, h, sx in drawn:
            if page_idx is not None and page_idx == self.current_page:
                pen = QPen(accent, border_width)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                rect = QRectF(
                    sx - border_width / 2 - 1,
                    margin - border_width / 2 - 1,
                    w + border_width + 2,
                    h + border_width + 2,
                )
                painter.drawRoundedRect(rect, border_radius, border_radius)

        painter.end()
        return composite, regions

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
            margin = 9
            avail_h = max(vh - margin * 2, 10)
            avail_w = max(vw - margin * 2, 10)
            gap = 10

            if self.view_mode == "single":
                # 항상 정확히 한 장만, 폭/높이 모두 맞춤
                self._row_anchor = self.current_page
                fit_scale = min(vw / page_w_pt, vh / page_h_pt)
                pix = target_page.get_pixmap(matrix=fitz.Matrix(fit_scale, fit_scale))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                self._page_regions = [(self.current_page, 0, img.width())]

            elif self.view_mode == "two":
                # 두 쪽 스프레드: 1쪽은 혼자 오른쪽에(왼쪽은 빈 칸), 이후 (2,3)(4,5)... 순으로
                # 짝-홀 페이지가 묶여 홀수 쪽이 항상 오른쪽에 오도록 한다(일반적인 책 펼침 방식).
                spread_start = self._two_mode_spread_start(self._row_anchor)
                self._row_anchor = spread_start
                if spread_start == 0:
                    real_indices = [0]
                    has_blank_left = True
                elif spread_start + 1 < len(self.doc):
                    real_indices = [spread_start, spread_start + 1]
                    has_blank_left = False
                else:
                    real_indices = [spread_start]  # 마지막 쪽이 짝을 못 찾는 경우 혼자 표시
                    has_blank_left = False

                if self.current_page not in real_indices:
                    self.current_page = spread_start

                ref_page = self.doc[real_indices[0]]
                rw_pt, rh_pt = ref_page.rect.width, ref_page.rect.height
                slot_count = len(real_indices) + (1 if has_blank_left else 0)
                max_scale_by_height = avail_h / max(rh_pt, 0.01)
                total_gap = gap * (slot_count - 1)
                rounding_slack = slot_count * 2
                scale_by_width = (avail_w - total_gap - rounding_slack) / max(slot_count * rw_pt, 0.01)
                scale = max(min(max_scale_by_height, scale_by_width), 0.01)

                slots = []  # (page_idx_or_None, QImage_or_None, w, h)
                if has_blank_left:
                    slots.append((None, None, int(rw_pt * scale), int(rh_pt * scale)))
                for idx in real_indices:
                    p = self.doc[idx]
                    pix = p.get_pixmap(matrix=fitz.Matrix(scale, scale))
                    pimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                    slots.append((idx, pimg, pimg.width(), pimg.height()))

                img, self._page_regions = self._composite_row(
                    slots, vw, vh, margin, gap, left_align=False
                )

            else:  # "wide"
                anchor_page = self.doc[self._row_anchor]
                anchor_w_pt, anchor_h_pt = anchor_page.rect.width, anchor_page.rect.height
                max_scale_by_height = avail_h / max(anchor_h_pt, 0.01)

                # 세로 높이를 꽉 채우는 크기만 고집하면, 듀얼모니터처럼 가로만 넓은 화면에서는
                # 페이지 자체가 (세로 기준으로) 이미 커서 몇 장 못 들어간다. 그래서 가로 공간이
                # 넉넉하면 최소 가독 폭(MIN_PAGE_DISPLAY_WIDTH) 안에서 페이지를 살짝 줄여서라도
                # 더 많은 장수(최대 MAX_PAGES_IN_ROW_WIDE)가 들어가도록 배율을 정한다.
                max_pages_available = min(len(self.doc) - self._row_anchor, MAX_PAGES_IN_ROW_WIDE)
                scale = max_scale_by_height
                for n in range(max_pages_available, 0, -1):
                    total_gap = gap * (n - 1)
                    if avail_w - total_gap <= 0:
                        continue
                    rounding_slack = n * 2  # 페이지별 픽셀 반올림 오차를 감안한 여유
                    scale_for_n = (avail_w - total_gap - rounding_slack) / (n * anchor_w_pt)
                    candidate_scale = min(scale_for_n, max_scale_by_height)
                    if candidate_scale * anchor_w_pt >= MIN_PAGE_DISPLAY_WIDTH or n == 1:
                        scale = candidate_scale
                        break

                shown = []  # (page_idx, QImage, disp_w)
                total_w = 0
                idx = self._row_anchor
                while idx < len(self.doc) and len(shown) < max_pages_available:
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

                # 화면이 아무리 넓어도, 보여줄 페이지가 적으면 가운데 대신 왼쪽부터 채운다
                slots = [(idx, im, w, im.height()) for idx, im, w in shown]
                seams = self._get_monitor_seams_in_viewport()
                img, self._page_regions = self._composite_row(
                    slots, vw, vh, margin, gap, left_align=True, seams=seams
                )

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
        self._navigate_to(value - 1)

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
        # 여러 페이지가 한 번에 보이는 상태라면, 겹치지 않도록 보이는 장수만큼 한 번에 넘긴다
        step = len(self._page_regions) if len(self._page_regions) > 1 else 1
        self.jump_by(-step)

    def next_page(self):
        step = len(self._page_regions) if len(self._page_regions) > 1 else 1
        self.jump_by(step)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.prev_page()
        elif event.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self.next_page()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.print_current_page()
        elif event.key() == Qt.Key_Escape and self.view_mode == "wide":
            self.set_view_mode(self._pre_wide_mode)
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
