# -*- coding: utf-8 -*-
"""Dosya yollari. Hem 'python gui.py' ile hem de derlenmis MetinBotu.exe ile
ayni sekilde calissin diye tek yerde tutulur."""

import os
import sys


def uygulama_dizini():
    """config.json, debug klasorleri ve Tesseract-OCR'in bulundugu klasor."""
    if getattr(sys, "frozen", False):          # PyInstaller ile derlenmis .exe
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def derlenmis_mi():
    return bool(getattr(sys, "frozen", False))


BURASI = uygulama_dizini()
