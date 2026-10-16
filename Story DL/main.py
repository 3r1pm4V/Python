"""Entry point — chạy: python main.py   (thêm --debug để ghi log chi tiết vào debug.log)"""
from app_core.bootstrap import setup

if __name__ == "__main__":
    setup()
    from gui.main_window import StoryLoaderGUI

    app = StoryLoaderGUI()
    app.mainloop()
