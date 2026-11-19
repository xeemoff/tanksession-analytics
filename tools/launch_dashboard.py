#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Select a local journal, bind the dashboard and open the browser.

No installation, game changes, downloads or data writes are performed.
Tk is optional: --demo, --data and --game-dir work without a graphical picker.
"""
import argparse
import os
import sys
import webbrowser

from dashboard import ROOT, create_server, load_goals


def journal_for_game(game_dir):
    root = os.path.abspath(os.path.expanduser(game_dir))
    if not os.path.isfile(os.path.join(root, 'paths.xml')):
        raise ValueError('В выбранной папке нет paths.xml. Выберите корневую папку игры.')
    return os.path.join(root, 'mods', 'configs', 'tanksession_analytics', 'battles.jsonl')


def choose_game_directory():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as error:
        raise RuntimeError('Tkinter не установлен. Используйте --game-dir "папка игры", '
                           '--data "путь к журналу" или --demo.') from error
    try:
        window = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError('Диалог выбора недоступен. Используйте --game-dir "папка игры", '
                           '--data "путь к журналу" или --demo.') from error
    try:
        window.withdraw()
        return filedialog.askdirectory(parent=window, title='Выберите папку «Мира танков» с paths.xml')
    finally:
        window.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Запуск локальной панели TankSession Analytics')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--demo', action='store_true', help='Открыть пример с вымышленными боями')
    source.add_argument('--game-dir', help='Корневая папка игры с paths.xml')
    source.add_argument('--data', help='Точный путь к существующему или ожидаемому battles.jsonl')
    parser.add_argument('--goals', default='', help='Локальный JSON с персональными целями')
    parser.add_argument('--port', type=int, default=8765, help='Порт панели; 0 — свободный порт')
    parser.add_argument('--no-browser', action='store_true', help='Показать адрес без открытия браузера')
    args = parser.parse_args(argv)
    try:
        if args.demo:
            path = os.path.join(ROOT, 'sample_data', 'battles.jsonl')
        elif args.data:
            path = os.path.abspath(os.path.expanduser(args.data))
        else:
            game_dir = args.game_dir or choose_game_directory()
            if not game_dir:
                print('Запуск отменён.')
                return 0
            path = journal_for_game(game_dir)
        goals_path = args.goals
        if args.demo and not goals_path:
            goals_path = os.path.join(ROOT, 'sample_data', 'goals.json')
        goals = load_goals(goals_path)
        server = create_server(path, goals, port=args.port)
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError) as error:
        if isinstance(error, OSError):
            print('Не удалось открыть файл или занять порт. Проверьте пути; '
                  'если панель уже запущена, используйте её адрес или --port 0.', file=sys.stderr)
        else:
            print('Запуск не выполнен: %s' % error, file=sys.stderr)
        return 1
    url = 'http://127.0.0.1:%d/' % server.server_port
    print('Панель: %s' % url, flush=True)
    print('Источник: %s' % path, flush=True)
    print('Для остановки нажмите Ctrl+C. Игровая интеграция требует отдельной проверки.', flush=True)
    try:
        if not args.no_browser:
            try:
                opened = webbrowser.open(url, new=2)
            except (OSError, webbrowser.Error):
                opened = False
            if not opened:
                print('Откройте адрес панели в браузере вручную.', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
