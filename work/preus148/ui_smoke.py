"""全商品OFFのローカル画面だけで時間帯編集を確認する。実注文の操作は行わない。"""

from pathlib import Path
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC


def main():
    """
    機能: ローカル静止画面のモーダル・時間帯保存・スマートフォン幅を検査する。
    引数: なし。
    返り値: None。画面と実行記録を当ファイル隣へ保存する。
    """
    here = Path(__file__).resolve().parent
    options = webdriver.EdgeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1440,1100')
    options.add_argument('--disable-gpu')
    service = Service(r'C:\Users\masay\.cache\selenium\msedgedriver\win64\147.0.3912.98\msedgedriver.exe')
    driver = webdriver.Edge(service=service, options=options)
    wait = WebDriverWait(driver, 15)
    try:
        driver.get('http://127.0.0.1:18098/')
        button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-product="NK225mini"] .settings-button')))
        button.click()
        wait.until(EC.visibility_of_element_located((By.ID, 'product-dialog')))
        assert len(driver.find_elements(By.CSS_SELECTOR, '.window-editor')) == 2
        assert driver.find_element(By.ID, 'product-save').get_attribute('disabled')
        driver.save_screenshot(str(here / '時間帯編集_標準.png'))
        driver.find_element(By.ID, 'product-window-add').click()
        assert len(driver.find_elements(By.CSS_SELECTOR, '.window-editor')) == 3
        rows = driver.find_elements(By.CSS_SELECTOR, '.window-editor')
        rows[-1].find_element(By.CSS_SELECTOR, '.window-row-top button').click()
        assert len(driver.find_elements(By.CSS_SELECTOR, '.window-editor')) == 2
        rows = driver.find_elements(By.CSS_SELECTOR, '.window-editor')
        end = rows[1].find_elements(By.CSS_SELECTOR, '.window-clock')[1]
        Select(end.find_element(By.TAG_NAME, 'select')).select_by_value('US_BEFORE')
        number = end.find_element(By.TAG_NAME, 'input')
        number.clear()
        number.send_keys('15')
        driver.find_element(By.ID, 'product-window-add').click()
        rows = driver.find_elements(By.CSS_SELECTOR, '.window-editor')
        start = rows[2].find_elements(By.CSS_SELECTOR, '.window-clock')[0]
        Select(start.find_element(By.TAG_NAME, 'select')).select_by_value('US_AFTER')
        method = rows[2].find_element(By.CSS_SELECTOR, 'label.field select')
        Select(method).select_by_value('NK225_PG04')
        driver.find_element(By.ID, 'product-save').click()
        wait.until(lambda d: not d.find_element(By.ID, 'product-dialog').get_attribute('open'))
        state = driver.execute_async_script("fetch('/api/settings').then(r=>r.json()).then(arguments[0])")
        item = next(x for x in state['instruments'] if x['product'] == 'NK225mini')
        assert item['mode'] == 'off'
        assert len(item['windows']) == 3
        assert item['windows'][1]['end'] == 'US_OPEN-00:15'
        assert item['windows'][2]['start'] == 'US_OPEN+00:15'
        driver.find_element(By.CSS_SELECTOR, '[data-product="NK225mini"] .settings-button').click()
        driver.save_screenshot(str(here / '時間帯編集_米国前後.png'))
        driver.set_window_size(420, 1000)
        driver.save_screenshot(str(here / '時間帯編集_狭幅.png'))
        no_overflow = driver.execute_script('return document.documentElement.scrollWidth <= window.innerWidth')
        assert no_overflow
        (here / '画面確認.json').write_text(json.dumps({'saved': item, 'horizontal_overflow': not no_overflow}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('UI_SMOKE_OK')
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
