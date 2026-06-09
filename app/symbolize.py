"""Best-effort ELF symbolication for crash addresses (epc1, excvaddr, ...).

Maps a firmware PC to "function (file:line)" using the firmware ELF's DWARF
debug info, via pyelftools (pure Python — no xtensa toolchain in the image).

ELF files live in ND_ELF_DIR (default /data/firmwares), named by firmware
version, e.g. "3.0.5.elf". Upload one (authenticated) with:

    curl -u admin:pass --data-binary @firmware.elf \\
         http://<host>:8081/elf/3.0.5

Everything here is best-effort: a missing ELF, missing pyelftools, or any parse
error yields None, and the dashboard falls back to showing the raw hex address.
"""
import bisect
import functools
import os

ELF_DIR = os.environ.get("ND_ELF_DIR", "/data/firmwares")


def elf_dir():
    return ELF_DIR


def _elf_path(fw):
    if not fw:
        return None
    fw = str(fw).strip()
    for name in (f"{fw}.elf", f"firmware-{fw}.elf", f"firmware_{fw}.elf",
                 os.path.join(fw, "firmware.elf")):
        p = os.path.join(ELF_DIR, name)
        if os.path.isfile(p):
            return p
    return None


def have_elf(fw):
    return _elf_path(fw) is not None


@functools.lru_cache(maxsize=8)
def _index(fw):
    """Build a lookup index for fw, or None. Cached per fw.

    Does ONE pass over the symbol table and DWARF line programs at load time,
    producing sorted arrays for O(log n) address lookups (so rendering a page
    with many crashes doesn't re-scan the ELF per address). Keeps the file
    handle open for pyelftools' lazy reads.
    """
    path = _elf_path(fw)
    if not path:
        return None
    try:
        from elftools.elf.elffile import ELFFile
    except Exception:
        return None
    try:
        fh = open(path, "rb")
        elf = ELFFile(fh)
        funcs = []
        symtab = elf.get_section_by_name(".symtab")
        if symtab is not None:
            for s in symtab.iter_symbols():
                try:
                    if s["st_info"]["type"] == "STT_FUNC" and s["st_value"]:
                        funcs.append(
                            (int(s["st_value"]), int(s["st_size"]), s.name))
                except Exception:
                    continue
        funcs.sort()

        # Flatten DWARF line programs into (addr, file, line) rows. End-of-
        # sequence rows are kept as (addr, None, None) gap markers so a lookup
        # landing past a function's code returns no spurious line.
        lines = []
        if elf.has_dwarf_info():
            try:
                dwarf = elf.get_dwarf_info()
                for cu in dwarf.iter_CUs():
                    lp = dwarf.line_program_for_CU(cu)
                    if lp is None:
                        continue
                    for e in lp.get_entries():
                        st = e.state
                        if st is None:
                            continue
                        if st.end_sequence:
                            lines.append((int(st.address), None, None))
                        else:
                            lines.append((int(st.address),
                                          _file_of(lp, st.file), st.line))
            except Exception:
                lines = []
        lines.sort(key=lambda x: x[0])
        addrs = [x[0] for x in lines]
        return {"funcs": funcs, "lines": lines, "addrs": addrs, "fh": fh}
    except Exception:
        return None


def _func_name(funcs, addr):
    """Nearest preceding STT_FUNC symbol containing addr."""
    if not funcs:
        return None
    i = bisect.bisect_right(funcs, (addr, 1 << 62, "")) - 1
    if i < 0:
        return None
    a, sz, name = funcs[i]
    if sz and addr >= a + sz:
        return None          # past the end of the nearest symbol
    return name


def _file_of(lp, file_index):
    try:
        entries = lp.header["file_entry"]
        ver = lp.header.get("version", 4)
        idx = file_index if ver >= 5 else file_index - 1
        if 0 <= idx < len(entries):
            name = entries[idx].name
            return name.decode() if isinstance(name, bytes) else name
    except Exception:
        pass
    return None


def _file_line(idx, addr):
    """O(log n) lookup of (file, line) for addr in the prebuilt line table."""
    addrs = idx["addrs"]
    if not addrs:
        return None
    i = bisect.bisect_right(addrs, addr) - 1
    if i < 0:
        return None
    _a, fn, ln = idx["lines"][i]
    if fn is None or ln is None:
        return None          # landed in a gap / past end-of-sequence
    return fn, ln


@functools.lru_cache(maxsize=512)
def decode(fw, addr):
    """Return 'func (file:line)' / 'func' / 'file:line' / None for a crash PC."""
    try:
        if not addr:
            return None
        idx = _index(fw)
        if not idx:
            return None
        name = _func_name(idx["funcs"], addr)
        loc = _file_line(idx, addr)
        if name and loc:
            return f"{name} ({loc[0]}:{loc[1]})"
        if name:
            return name
        if loc:
            return f"{loc[0]}:{loc[1]}"
        return None
    except Exception:
        return None


def clear_cache():
    decode.cache_clear()
    _index.cache_clear()
