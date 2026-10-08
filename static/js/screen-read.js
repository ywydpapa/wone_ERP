(function(root) {
    const BLOCK_TAGS = new Set([
        'DIV', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER', 'FORM', 'FIELDSET', 'LABEL',
        'UL', 'OL', 'DL', 'P', 'LI', 'DT', 'DD',
        'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
        'TABLE', 'TR', 'TD', 'TH', 'THEAD', 'TBODY', 'TFOOT',
        'BLOCKQUOTE', 'PRE', 'FIGURE', 'FIGCAPTION',
        'NAV', 'ASIDE', 'MAIN', 'DETAILS', 'SUMMARY',
    ]);
    const CONTROL_SEL = 'button, input, select, textarea, [role=button], .btn';
    const SKIP_SEL = 'script, style, template, noscript';

    function visible(el) {
        if (!el || el.nodeType !== 1) return false;
        if (el.matches(SKIP_SEL)) return false;
        if (el.hidden || el.getAttribute('aria-hidden') === 'true') return false;
        if (el.classList.contains('visually-hidden') || el.classList.contains('sr-only')) return false;
        // 닫힌 details 내부도 rect 반환. checkVisibility로 판정
        return el.checkVisibility({ visibilityProperty: true, opacityProperty: true });
    }

    // 숨은 자손, 컨트롤 제외. select option 누출 방지
    function cellText(el) {
        let buf = '';
        (function dig(node) {
            node.childNodes.forEach(child => {
                if (child.nodeType === 3) {
                    buf += child.textContent;
                    return;
                }
                if (child.nodeType !== 1 || !visible(child) || child.matches(CONTROL_SEL)) return;
                dig(child);
            });
        })(el);
        return buf.replace(/\s+/g, ' ').trim();
    }

    function labelText(el) {
        return cellText(el).replace(/\*/g, '').replace(/\(.*?\)/g, '').replace(/\s+/g, ' ').trim();
    }

    function fieldValue(el) {
        if (el.tagName === 'SELECT') return el.value ? el.options[el.selectedIndex].textContent.trim() : '선택 안 함';
        if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? '선택됨' : '선택 안 됨';
        if (el.type === 'file') return el.files.length ? '파일 있음' : '파일 없음';
        return el.value || '비어 있음';
    }

    // 라벨 옆칸(fg-field, mini-stat-value). 입력칸 있으면 입력값, 없으면 텍스트 기준
    function fieldOf(container) {
        const sel = 'input, select, textarea';
        const ctrl = container.matches(sel) ? container : container.querySelector(sel);
        return ctrl ? fieldValue(ctrl) : cellText(container);
    }

    function isBlocky(el) {
        return BLOCK_TAGS.has(el.tagName);
    }

    function hasBlockKid(el) {
        return [...el.children].some(k => visible(k) && isBlocky(k));
    }

    // colspan/rowspan 반영해 열별 헤더 맵 구성
    function headerMap(table) {
        const rows = [...table.querySelectorAll('thead tr')];
        const grid = [];
        const occupied = [];
        rows.forEach((tr, r) => {
            occupied[r] = occupied[r] || [];
            let col = 0;
            [...tr.children].forEach(cell => {
                while (occupied[r][col]) col++;
                const span = parseInt(cell.getAttribute('colspan') || '1', 10);
                const rspan = parseInt(cell.getAttribute('rowspan') || '1', 10);
                const text = cellText(cell);
                const hide = !visible(cell);
                for (let c = col; c < col + span; c++) {
                    grid[c] = grid[c] || [];
                    grid[c].push({ text, hide });
                    for (let rr = r + 1; rr < r + rspan; rr++) {
                        occupied[rr] = occupied[rr] || [];
                        occupied[rr][c] = true;
                    }
                }
                col += span;
            });
        });
        return grid.map(cells => ({
            text: [...new Set(cells.map(c => c.text).filter(Boolean))].join(' '),
            hidden: cells.some(c => c.hide),
        }));
    }

    // colspan 셀은 헤더 라벨 제외
    function rowParts(tr, header) {
        let col = 0;
        const parts = [];
        [...tr.children].forEach(cell => {
            const span = parseInt(cell.getAttribute('colspan') || '1', 10);
            const start = col;
            col += span;
            if (!visible(cell)) return;
            const h = header[start];
            if (h && h.hidden) return;
            const v = cellText(cell);
            if (!v) return;
            parts.push(span === 1 && h && h.text ? h.text + ' ' + v : v);
        });
        return parts;
    }

    function tableLines(table) {
        const header = headerMap(table);
        const lines = [];
        const cap = table.querySelector('caption');
        if (cap && visible(cap)) lines.push(cellText(cap));
        const rows = [...table.querySelectorAll('tbody tr')].filter(visible);
        rows.slice(0, 20).forEach((tr, i) => {
            const parts = rowParts(tr, header);
            if (parts.length) lines.push((i + 1) + '행, ' + parts.join(', '));
        });
        if (rows.length > 20) lines.push('이하 ' + (rows.length - 20) + '행 생략');
        [...table.querySelectorAll('tfoot tr')].filter(visible).forEach(tr => {
            const parts = rowParts(tr, header);
            if (parts.length) lines.push('합계, ' + parts.join(', '));
        });
        return lines;
    }

    function blockOf(cur) {
        if (cur.tagName === 'TD' || cur.tagName === 'TH') {
            const table = cur.closest('table');
            const tr = cur.parentElement;
            const header = headerMap(table);
            let col = 0;
            for (const sib of tr.children) {
                const span = parseInt(sib.getAttribute('colspan') || '1', 10);
                if (sib === cur) {
                    const h = header[col];
                    const v = cellText(cur);
                    return span === 1 && h && h.text ? h.text + ' ' + v : v;
                }
                col += span;
            }
            return cellText(cur);
        }
        if (cur.tagName === 'LABEL' && cur.htmlFor) {
            const field = document.getElementById(cur.htmlFor);
            return field ? labelText(cur) + ', ' + fieldValue(field) : null;
        }
        if (cur.classList.contains('stat-info')) return cellText(cur);
        if ([...cur.classList].some(c => c.endsWith('-label'))) {
            const next = cur.nextElementSibling;
            return next && visible(next) ? labelText(cur) + ', ' + fieldOf(next) : cellText(cur);
        }
        if (cur.tagName === 'DT') {
            const parts = [cellText(cur)];
            let n = cur.nextElementSibling;
            while (n && n.tagName === 'DD') {
                parts.push(cellText(n));
                n = n.nextElementSibling;
            }
            return parts.join(', ');
        }
        if (isBlocky(cur) && !hasBlockKid(cur)) return cellText(cur);
        return null;
    }

    function blockText(el) {
        let cur = el;
        while (cur && cur.nodeType === 1) {
            if (visible(cur)) {
                const t = blockOf(cur);
                if (t !== null) return t || '';
            }
            if (cur.id === 'main') break;
            cur = cur.parentElement;
        }
        return '';
    }

    function walk(el, out) {
        const kids = [...el.childNodes];
        let buf = '';
        const flush = () => {
            const t = buf.replace(/\s+/g, ' ').trim();
            if (t) out.push(t);
            buf = '';
        };
        for (let i = 0; i < kids.length; i++) {
            const node = kids[i];
            if (node.nodeType === 3) {
                buf += node.textContent;
                continue;
            }
            if (node.nodeType !== 1) continue;
            const cur = node;
            if (!visible(cur)) continue;
            if (cur.matches(CONTROL_SEL)) {
                // label 없이 aria-label만 있는 칸 (기간 종료 등)
                if (cur.matches('input, select, textarea') && cur.getAttribute('aria-label')) {
                    flush();
                    out.push(cur.getAttribute('aria-label') + ', ' + fieldValue(cur));
                }
                continue;
            }

            if (cur.tagName === 'TABLE') {
                flush();
                out.push(...tableLines(cur));
                continue;
            }
            if (cur.tagName === 'LABEL' && cur.htmlFor) {
                flush();
                const field = document.getElementById(cur.htmlFor);
                if (field) out.push(labelText(cur) + ', ' + fieldValue(field));
                continue;
            }
            if (cur.classList.contains('stat-info')) {
                flush();
                const t = cellText(cur);
                if (t) out.push(t);
                continue;
            }
            if ([...cur.classList].some(c => c.endsWith('-label'))) {
                flush();
                let j = i + 1;
                while (j < kids.length && kids[j].nodeType === 3 && !kids[j].textContent.trim()) j++;
                const next = j < kids.length && kids[j].nodeType === 1 ? kids[j] : null;
                if (next && visible(next)) {
                    out.push(labelText(cur) + ', ' + fieldOf(next));
                    i = j;
                } else {
                    const t = cellText(cur);
                    if (t) out.push(t);
                }
                continue;
            }
            if (cur.tagName === 'DT') {
                flush();
                const parts = [cellText(cur)];
                let j = i + 1;
                while (j < kids.length) {
                    const n = kids[j];
                    if (n.nodeType === 1 && n.tagName === 'DD' && visible(n)) {
                        parts.push(cellText(n));
                        j++;
                    } else if (n.nodeType === 3 && !n.textContent.trim()) {
                        j++;
                    } else {
                        break;
                    }
                }
                if (parts[0]) out.push(parts.join(', '));
                i = j - 1;
                continue;
            }
            if (isBlocky(cur)) {
                flush();
                if (hasBlockKid(cur)) {
                    walk(cur, out);
                } else {
                    const t = cellText(cur);
                    if (t) out.push(t);
                }
            } else {
                buf += ' ' + cellText(cur);
            }
        }
        flush();
    }

    function lines(el) {
        const out = [];
        walk(el, out);
        return out.filter(t => /[\p{L}\p{N}]/u.test(t));
    }

    root.ScreenRead = { lines, blockText };
})(window);
