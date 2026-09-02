import pytest

pytestmark = pytest.mark.django_db


def _open_book_view(page):
    page.click('#view-book-btn')
    page.wait_for_selector("#book-pagination[style*='flex']")


def test_select_all_checks_and_unchecks_current_page(venues, page_with_bearer):
    page = page_with_bearer
    _open_book_view(page)

    select_all = page.locator('#book-select-all')
    boxes = page.locator('.venue-row.book-visible input[type=checkbox]')

    assert boxes.evaluate_all('els => els.filter(e => e.checked).length') == 0

    select_all.check()
    count = boxes.count()
    assert count > 0
    assert boxes.evaluate_all('els => els.filter(e => e.checked).length') == count
    assert page.locator('#stamp-count').inner_text() == str(count)

    select_all.uncheck()
    assert boxes.evaluate_all('els => els.filter(e => e.checked).length') == 0
    assert page.locator('#stamp-count').inner_text() == '0'


def test_select_all_goes_indeterminate_on_partial_selection(venues, page_with_bearer):
    page = page_with_bearer
    _open_book_view(page)

    select_all = page.locator('#book-select-all')
    boxes = page.locator('.venue-row.book-visible input[type=checkbox]')

    boxes.nth(0).check()
    boxes.nth(1).check()

    assert select_all.evaluate('el => el.indeterminate') is True
    assert select_all.evaluate('el => el.checked') is False

    for i in range(boxes.count()):
        boxes.nth(i).check()

    assert select_all.evaluate('el => el.checked') is True
    assert select_all.evaluate('el => el.indeterminate') is False


def test_select_all_is_scoped_to_the_current_page(venues, page_with_bearer):
    page = page_with_bearer
    _open_book_view(page)

    page.locator('#book-select-all').check()
    page.click('#book-next-btn')
    page.wait_for_function("document.querySelector('#book-page-indicator').textContent.includes('2 of')")

    select_all = page.locator('#book-select-all')
    assert select_all.evaluate('el => el.checked') is False
    assert select_all.evaluate('el => el.indeterminate') is False

    boxes = page.locator('.venue-row.book-visible input[type=checkbox]')
    assert boxes.evaluate_all('els => els.filter(e => e.checked).length') == 0


def test_select_all_is_hidden_in_list_view(venues, page_with_bearer):
    page = page_with_bearer
    _open_book_view(page)

    page.click('#view-list-btn')
    display = page.locator('#book-pagination').evaluate('el => getComputedStyle(el).display')
    assert display == 'none'
