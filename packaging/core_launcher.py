"""PyInstaller console entry for the Qt-free desktop sidecar."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from ysu_net.desktop.app import main
    raise SystemExit(main())
