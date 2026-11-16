"""Convert the exact saved Word document with an isolated LibreOffice profile."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class ExportError(RuntimeError):
    pass


def export_pdf(docx):
    docx = Path(docx).resolve()
    target = docx.with_suffix('.pdf')
    if target.exists() and target.stat().st_mtime >= docx.stat().st_mtime and target.read_bytes().startswith(b'%PDF-'):
        return target
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice'
    executable = os.environ.get('SOFFICE_PATH') or (str(bundled) if bundled.is_file() else shutil.which('soffice'))
    if not executable:
        raise ExportError('PDF uchun LibreOffice topilmadi.')
    try:
        with tempfile.TemporaryDirectory(prefix='contract-pdf-') as tmp:
            folder = Path(tmp)
            subprocess.run([executable, '-env:UserInstallation=' + (folder/'profile').as_uri(),
                            '--headless', '--convert-to', 'pdf', '--outdir', str(folder), str(docx)],
                           timeout=45, capture_output=True, check=True)
            result = folder / (docx.stem + '.pdf')
            if not result.is_file() or not result.read_bytes().startswith(b'%PDF-'):
                raise ExportError('PDF fayli yaratilmagan.')
            temporary = target.with_suffix('.pdf.tmp')
            temporary.write_bytes(result.read_bytes())
            temporary.replace(target)
    except (OSError, subprocess.SubprocessError):
        raise ExportError('PDF yaratishda xato. Qayta urinib ko‘ring.') from None
    return target
