import base64
import json
import scrapy
import time
from datetime import timedelta
from time import time as start_time

class ProxySpider(scrapy.Spider):
    name = "proxy_spider"
    allowed_domains = ["free-proxy.cz", "test-rg8.ddns.net"]
    start_urls = ["http://free-proxy.cz/en/"]

    # Личный токен пользователя
    personal_token = "t_6fad03a2"

    # Ограничиваем количество страниц
    max_pages = 3

    # Результаты
    results = {}
    start = start_time()  # Запускаем таймер

    def start_requests(self):
        # Начинаем с первой страницы и запрашиваем токен для каждой страницы
        yield scrapy.Request(
            url="https://test-rg8.ddns.net/api/get_token",
            callback=self.get_token_for_page,
            meta={'page_num': 1},
            dont_filter=True,  # Отключаем фильтрацию дубликатов
            errback=self.handle_error
        )

    def get_token_for_page(self, response):
        # Извлекаем куки из заголовка Set-Cookie
        cookies = response.headers.getlist('Set-Cookie')
        form_token = None

        for cookie in cookies:
            cookie_str = cookie.decode('utf-8')
            if 'form_token' in cookie_str:
                form_token = cookie_str.split('=')[1].split(';')[0]
                break

        if not form_token:
            self.logger.error("Не удалось получить form_token.")
            return

        page_num = response.meta['page_num']
        self.logger.info(f"Получен form_token для страницы {page_num}: {form_token}")


        # Переходим к парсингу прокси с использованием токена
        page_url = f"http://free-proxy.cz/en/proxylist/country/all/all/ping/all/{page_num}"
        yield scrapy.Request(
            url=page_url,
            callback=self.parse_proxies,
            headers={'Cookie': f'x-user_id={self.personal_token}; form_token={form_token}'},
            meta={'form_token': form_token, 'page_num': page_num},
            dont_filter=True,  # Отключаем фильтрацию дубликатов
            errback=self.handle_error
        )

    def parse_proxies(self, response):
        form_token = response.meta.get('form_token')
        page_num = response.meta.get('page_num')

        # Получаем строки с IP и портами
        rows = response.xpath('//*[@id="proxy_list"]/tbody/tr')
        proxies = []

        for row in rows:
            encoded_ip_script = row.xpath('.//script[contains(text(), "Base64.decode")]/text()').get()

            if encoded_ip_script:
                start = encoded_ip_script.find('Base64.decode("') + len('Base64.decode("')
                end = encoded_ip_script.find('")', start)
                encoded_ip = encoded_ip_script[start:end]

                decoded_ip = base64.b64decode(encoded_ip).decode("utf-8")
                port = row.xpath('.//span[contains(@class, "fport")]/text()').get()

                if decoded_ip and port:
                    proxies.append(f"{decoded_ip}:{port}")

        # Преобразуем список прокси в строку с разделителями запятой
        proxies_str = ', '.join(proxies)

        # Отправляем прокси на сервер
        yield scrapy.Request(
            url="https://test-rg8.ddns.net/api/post_proxies",
            method="POST",
            body=json.dumps({
                "user_id": self.personal_token,
                "len": len(proxies),  # Количество прокси
                "proxies": proxies_str  # Прокси в виде строки через запятую
            }),
            headers={
                'Content-Type': 'application/json',
                'Cookie': f'form_token={form_token}; x-user_id={self.personal_token}'
            },
            callback=self.handle_post_response,
            meta={'form_token': form_token, 'proxies': proxies_str, 'page_num': page_num},
            dont_filter=True,  # Отключаем фильтрацию дубликатов
            errback=self.handle_error
        )

    def handle_post_response(self, response):
        proxies = response.meta.get('proxies')
        page_num = response.meta.get('page_num')

        # Получаем save_id из ответа
        data = json.loads(response.text)
        save_id = data.get('save_id')

        if save_id:
            self.results[save_id] = proxies.split(', ')
            self.logger.info(f"Успешно сохранен save_id: {save_id} для страницы {page_num}")
        else:
            self.logger.error(f"Не удалось получить save_id для страницы {page_num}")

        # Переходим к следующей странице, если еще не все обработаны
        next_page = page_num + 1
        if next_page <= self.max_pages:
            # Запрашиваем новый токен для следующей страницы
            yield scrapy.Request(
                url="https://test-rg8.ddns.net/api/get_token",
                callback=self.get_token_for_page,
                meta={'page_num': next_page},
                dont_filter=True,  # Отключаем фильтрацию дубликатов
                errback=self.handle_error
            )
        else:
            # Если все страницы обработаны, сохраняем результаты
            self.save_results()

    def save_results(self):
        # Сохраняем результаты в файл results.json
        with open('results.json', 'w') as f:
            json.dump(self.results, f, indent=4)

        # Сохраняем время выполнения в файл time.txt
        execution_time = timedelta(seconds=int(time.time() - self.start))
        with open('time.txt', 'w') as time_file:
            time_file.write(str(execution_time))

    def handle_error(self, failure):
        self.logger.error(f"Произошла ошибка: {failure.value}")