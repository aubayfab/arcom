"""Rassemble les licences des composants tiers embarqués dans un livrable Windows.

Usage : python collect_licenses.py <sortie.txt> [--path <dossier>] [--pyinstaller]

  sans --path   dépendances de requirements.txt (récursivement), lues dans l'environnement courant
                (exécutable PyInstaller, compilé depuis .venv)
  --path        tous les paquets installés dans ce dossier (python\\pkgs de la version portable)
  --pyinstaller ajoute Python et le chargeur PyInstaller, inclus dans l'exécutable

Pour chaque paquet : nom, version, licence, adresse du projet et textes de licence qu'il fournit.
pystray est sous LGPL-3.0 : le livrable doit être accompagné de ces textes, et ses sources (comme
les nôtres) restent disponibles pour qui voudrait le remplacer par une version modifiée.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)

# Les paquets winrt-* (pywinrt) déclarent MIT sans fournir le texte ; repris de leur dépôt.
PYWINRT_LICENSE = """\
MIT License

Copyright (c) Microsoft Corporation. All rights reserved.
Copyright (c) 2021-2025 David Lechner <david@pybricks.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(line: str) -> str:
    return re.split(r"[\s<>=!~\[(;]", line.strip(), maxsplit=1)[0]


def runtime_closure(installed: dict[str, md.Distribution]) -> dict[str, md.Distribution]:
    """requirements.txt et leurs dépendances ; celles d'autres plateformes ne sont pas installées."""
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    todo = [requirement_name(x) for x in lines if x.strip() and not x.lstrip().startswith("#")]
    found: dict[str, md.Distribution] = {}
    while todo:
        name = norm(todo.pop())
        if name in found or name not in installed:
            continue
        found[name] = installed[name]
        for req in installed[name].requires or []:
            if "extra ==" not in req:
                todo.append(requirement_name(req))
    return found


def license_of(dist: md.Distribution) -> str:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return "; ".join(classifiers) or (meta.get("License") or "?").splitlines()[0]


def project_url(dist: md.Distribution) -> str:
    urls = [u.split(",", 1)[-1].strip() for u in dist.metadata.get_all("Project-URL") or []]
    return dist.metadata.get("Home-page") or next(iter(urls), "")


def license_texts(dist: md.Distribution) -> list[tuple[str, str]]:
    texts = []
    for f in dist.files or []:
        parts = Path(str(f)).parts
        if parts and parts[0].endswith(".dist-info") and LICENSE_FILE.search(parts[-1]):
            texts.append((str(f), Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace")))
    if not texts and norm(dist.metadata["Name"]).startswith("winrt-"):
        texts.append(("pywinrt LICENSE", PYWINRT_LICENSE))
    return texts


def section(title: str, body: str) -> str:
    return f"{'=' * 78}\n{title}\n{'=' * 78}\n\n{body.strip()}\n\n"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("output")
    p.add_argument("--path", help="dossier de paquets installés (python\\pkgs)")
    p.add_argument("--pyinstaller", action="store_true", help="ajoute Python et le chargeur PyInstaller")
    args = p.parse_args()

    installed = {norm(d.metadata["Name"]): d
                 for d in md.distributions(**({"path": [args.path]} if args.path else {}))}
    dists = installed if args.path else runtime_closure(installed)

    out = ["Télécommande Arcom — composants tiers et leurs licences\n\n"
           "Le code de la Télécommande Arcom est sous licence MIT (voir LICENCE.txt).\n"
           "Ce livrable contient aussi les composants suivants, chacun sous sa propre licence.\n\n"]
    summary = [f"  {d.metadata['Name']} {d.version} — {license_of(d)}"
               for d in sorted(dists.values(), key=lambda d: norm(d.metadata["Name"]))]
    if args.pyinstaller:
        summary[:0] = [f"  Python {sys.version.split()[0]} — PSF-2.0",
                       f"  Chargeur PyInstaller {md.version('pyinstaller')} — GPL-2.0 avec exception "
                       "(distribution libre avec tout programme)"]
    out.append("\n".join(summary) + "\n\n")

    if args.pyinstaller:
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
        out.append(section(f"Python {sys.version.split()[0]} — https://www.python.org",
                           python_license.read_text(encoding="utf-8", errors="replace")))
        pyinstaller = md.distribution("pyinstaller")
        out.append(section(f"PyInstaller {pyinstaller.version} (chargeur) — https://pyinstaller.org",
                           "\n\n".join(text for _, text in license_texts(pyinstaller))))
    for d in sorted(dists.values(), key=lambda d: norm(d.metadata["Name"])):
        texts = license_texts(d)
        body = "\n\n".join(f"--- {name} ---\n\n{text.strip()}" for name, text in texts) if texts else \
            f"Licence {license_of(d)} : texte non fourni par le paquet, voir {project_url(d)}"
        out.append(section(f"{d.metadata['Name']} {d.version} — {license_of(d)} — {project_url(d)}", body))

    Path(args.output).write_text("".join(out), encoding="utf-8-sig", newline="\r\n")
    print(f"{args.output} : {len(summary)} composants")


if __name__ == "__main__":
    main()
