"""Convert the exact saved Word document with an isolated LibreOffice profile."""
import glob
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

TIMEOUT = 120


class ExportError(RuntimeError):
    pass


def candidates():
    """LibreOffice executables in priority order, without duplicates."""
    found = []
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice'
    options = [os.environ.get('SOFFICE_PATH'), shutil.which('soffice'), shutil.which('libreoffice'),
               '/usr/bin/soffice', '/usr/lib/libreoffice/program/soffice',
               *sorted(glob.glob('/opt/libreoffice*/program/soffice'), reverse=True),
               '/snap/bin/libreoffice', str(bundled)]
    for option in options:
        if option and Path(option).is_file() and os.access(option, os.X_OK):
            real = str(Path(option).resolve())
            if real not in found:
                found.append(real)
    return found


def available():
    return bool(candidates())


def convert_bytes(docx_bytes):
    """Return PDF bytes for DOCX bytes. Tries every LibreOffice found, each twice."""
    executables = candidates()
    if not executables:
        raise ExportError('PDF uchun LibreOffice topilmadi. Serverga libreoffice-writer o‘rnating.')
    last = 'noma’lum xato'
    for executable in executables:
        for attempt in range(2):
            with tempfile.TemporaryDirectory(prefix='contract-pdf-') as tmp:
                folder = Path(tmp)
                source = folder / 'document.docx'
                source.write_bytes(docx_bytes)
                env = dict(os.environ, HOME=str(folder), SAL_USE_VCLPLUGIN='svp')
                try:
                    done = subprocess.run(
                        [executable, '-env:UserInstallation=' + (folder / 'profile').as_uri(),
                         '--headless', '--norestore', '--nologo', '--nofirststartwizard',
                         '--convert-to', 'pdf', '--outdir', str(folder / 'out'), str(source)],
                        timeout=TIMEOUT, capture_output=True, env=env, stdin=subprocess.DEVNULL)
                except subprocess.TimeoutExpired:
                    last = f'{executable}: {TIMEOUT} soniyada tugamadi'
                    logging.warning('pdf convert timeout executable=%s attempt=%d', executable, attempt + 1)
                    continue
                except OSError as error:
                    last = f'{executable}: {error}'
                    logging.warning('pdf convert cannot start executable=%s error=%s', executable, error)
                    break
                result = folder / 'out' / 'document.pdf'
                if result.is_file() and result.read_bytes().startswith(b'%PDF-'):
                    return result.read_bytes()
                stderr = done.stderr.decode(errors='replace').strip()[-400:]
                last = f'{executable}: kod {done.returncode} {stderr}'
                logging.warning('pdf convert failed executable=%s attempt=%d code=%s stderr=%s',
                                executable, attempt + 1, done.returncode, stderr)
    raise ExportError('PDF yaratishda xato: ' + last)


def page_count(pdf_bytes):
    return len(re.findall(rb'/Type\s*/Page\b(?!s)', pdf_bytes))


def page_texts(pdf_bytes):
    """Text of each page (needs Poppler's pdftotext), or None if unavailable."""
    tool = shutil.which('pdftotext')
    if not tool:
        return None
    with tempfile.TemporaryDirectory(prefix='contract-pages-') as tmp:
        path = Path(tmp) / 'document.pdf'
        path.write_bytes(pdf_bytes)
        try:
            done = subprocess.run([tool, '-enc', 'UTF-8', str(path), '-'], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
    if done.returncode:
        return None
    pages = done.stdout.decode('utf-8', errors='replace').split('\f')
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def export_pdf(docx):
    docx = Path(docx).resolve()
    target = docx.with_suffix('.pdf')
    if target.exists() and target.stat().st_mtime >= docx.stat().st_mtime and target.read_bytes().startswith(b'%PDF-'):
        return target
    try:
        data = convert_bytes(docx.read_bytes())
        temporary = target.with_suffix('.pdf.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    except OSError as error:
        logging.warning('pdf write failed: %s', error)
        raise ExportError('PDF faylini saqlashda xato.') from None
    return target
