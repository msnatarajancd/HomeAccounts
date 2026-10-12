// Column filters and sorting operate on confirmed records only.
export function mountTransactionGrid(container, {records, columns, escape, newRecordIds}) {
  if (!container) return;
  const query = new URLSearchParams(location.search);
  let sort = columns.some(column => column.key === query.get('sort')) ? query.get('sort') : 'date';
  let direction = query.get('sort_dir') === 'asc' ? 'asc' : 'desc';
  const filters = Object.fromEntries(columns.map(column => [column.key, query.get('column_' + column.key) || '']));
  const value = (row, key) => key.startsWith('custom_') ? JSON.parse(row.custom_fields || '{}')[key] ?? '' : row[key] ?? '';
  container.innerHTML = `<div class="grid-tools"><p id="grid-count" class="field-hint" role="status"></p><button type="button" id="clear-column-filters">Clear column filters</button></div><div class="table-wrap"><table aria-label="Confirmed transactions"><thead><tr>${columns.map(column => `<th scope="col" data-column="${escape(column.key)}"><button type="button" class="sort-column" data-sort="${escape(column.key)}" aria-label="Sort by ${escape(column.label)}">${escape(column.label)} <span class="sort-indicator" aria-hidden="true"></span></button><label class="sr-only" for="filter-${escape(column.key)}">Filter ${escape(column.label)}</label><input id="filter-${escape(column.key)}" class="column-filter" type="search" data-filter="${escape(column.key)}" value="${escape(filters[column.key])}" placeholder="Filter ${escape(column.label)}"></th>`).join('')}<th scope="col">Actions</th></tr></thead><tbody></tbody></table></div>`;
  function render() {
    const filtered = records.filter(row => columns.every(column => String(value(row, column.key)).toLocaleLowerCase().includes(filters[column.key].trim().toLocaleLowerCase())));
    const column = columns.find(item => item.key === sort);
    filtered.sort((left, right) => {
      const a = value(left, sort), b = value(right, sort);
      const validA = String(a).trim() !== '' && Number.isFinite(Number(a));
      const validB = String(b).trim() !== '' && Number.isFinite(Number(b));
      if (column?.numeric && validA !== validB) return validA ? -1 : 1;
      const lowerA = String(a).toLocaleLowerCase(), lowerB = String(b).toLocaleLowerCase();
      const comparison = column?.numeric && validA && validB
        ? Number(a) - Number(b) : lowerA < lowerB ? -1 : lowerA > lowerB ? 1 : 0;
      return direction === 'asc' ? comparison : -comparison;
    });
    container.querySelector('tbody').innerHTML = filtered.length ? filtered.map(row => `<tr data-transaction-id="${escape(row.id)}" class="${newRecordIds.has(row.id) ? 'just-added' : ''}">${columns.map(column => `<td title="${escape(value(row, column.key))}">${escape(value(row, column.key))}</td>`).join('')}<td><button data-edit="${escape(row.id)}">Edit</button> <button class="danger" data-delete="${escape(row.id)}">Remove</button></td></tr>`).join('') : `<tr><td colspan="${columns.length + 1}">No matching records. Clear a column filter or change the page filters.</td></tr>`;
    container.querySelector('#grid-count').textContent = `${filtered.length} of ${records.length} records shown. Select a heading to sort; type below it to filter. Export uses these filters and this order.`;
    for (const heading of container.querySelectorAll('[data-column]')) {
      const selected = heading.dataset.column === sort;
      heading.setAttribute('aria-sort', selected ? (direction === 'asc' ? 'ascending' : 'descending') : 'none');
      heading.querySelector('.sort-indicator').textContent = selected ? (direction === 'asc' ? '↑' : '↓') : '↕';
    }
    const url = new URL(location.href);
    for (const [key, text] of Object.entries(filters)) {
      if (text.trim()) url.searchParams.set('column_' + key, text);
      else url.searchParams.delete('column_' + key);
    }
    url.searchParams.set('sort', sort); url.searchParams.set('sort_dir', direction);
    history.replaceState(history.state, '', url.pathname + url.search);
  }
  container.addEventListener('input', event => {
    if (!event.target.matches('[data-filter]')) return;
    filters[event.target.dataset.filter] = event.target.value; render();
  });
  container.addEventListener('click', event => {
    const button = event.target.closest('[data-sort]');
    if (button) { direction = sort === button.dataset.sort && direction === 'asc' ? 'desc' : 'asc'; sort = button.dataset.sort; render(); }
    if (event.target.closest('#clear-column-filters')) {
      for (const input of container.querySelectorAll('[data-filter]')) { input.value = ''; filters[input.dataset.filter] = ''; }
      render(); container.querySelector('[data-filter]')?.focus();
    }
  });
  render();
}
