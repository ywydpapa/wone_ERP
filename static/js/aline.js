document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-aline]');
    if (!btn) return;
    var box = btn.closest('.aline');
    var body = box.querySelector('tbody');
    var row = btn.closest('tr');
    var act = btn.dataset.aline;
    if (act === 'add') {
        body.insertAdjacentHTML('beforeend', box.querySelector('.aline-tpl').innerHTML);
    } else if (act === 'del') {
        row.remove();
    } else if (act === 'up') {
        var prev = row.previousElementSibling;
        if (prev && !prev.classList.contains('aline-fixed')) body.insertBefore(row, prev);
    } else if (act === 'down' && row.nextElementSibling) {
        body.insertBefore(row.nextElementSibling, row);
    }
});
