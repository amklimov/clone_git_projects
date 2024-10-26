import requests
import os
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor
import re

# Настройки
GITLAB_URL = "https://gitlab.com"  # URL вашего GitLab
GROUP_ID = "ID_Group"                        # ID вашей группы Git, в которой лежат все проекты и репозитории
ACCESS_TOKEN = "My-Token"                  # Ваш личный токен доступа
TIMEOUT = 60                               # Таймаут для HTTP-запросов
CLONE_TIMEOUT = 1800                        # Таймаут для клонирования (увеличен до 30 минут)
MAX_WORKERS = 6                            # Количество потоков для параллельного клонирования


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',  # Формат логов
    handlers=[
        logging.FileHandler('app.log', mode='w'),  # Логирование в файл
        logging.StreamHandler()  # Логирование в консоль
    ]
)
logger = logging.getLogger(__name__)


# Функция для преобразования имени проекта в формат "slug" (нижний регистр, дефисы вместо пробелов и прочих символов)
def slugify_project_name(name):
    # Заменить пробелы и некорректные символы на дефисы
    name = re.sub(r'[^\w\s-]', '', name)  # Удалить всё кроме букв, цифр, пробелов и дефисов
    name = re.sub(r'\s+', '-', name)      # Заменить пробелы на дефисы
    return name.lower()                   # Преобразовать в нижний регистр


# Функция для клонирования проекта
def clone_project(project, path):
    project_name = project['name']
    clone_url = project['ssh_url_to_repo']  # Использование SSH URL для клонирования

    # Преобразуем имя проекта в slug-формат (как делает git clone)
    project_slug = slugify_project_name(project_name)
    project_path = os.path.join(path, project_slug)

    if not os.path.exists(project_path):
        logger.info(f"Клонирование проекта {project_name} в {project_path}")
        try:
            # Клонирование всех веток и полной истории
            subprocess.run(['git', 'clone', clone_url, project_path], check=True, timeout=CLONE_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.error(f"Клонирование проекта {project_name} превысило таймаут и было прервано")
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка клонирования проекта {project_name}: {e}")
    else:
        logger.info(f"Проект {project_name} уже существует в {path}, пропускаем...")


# Функция для получения всех проектов в группе и её подгруппах
def get_projects(group_id, access_token, path):
    # Получаем проекты в группе
    page = 1
    while True:
        try:
            response = requests.get(
                f"{GITLAB_URL}/api/v4/groups/{group_id}/projects",
                headers={"PRIVATE-TOKEN": access_token},
                params={"per_page": 100, "page": page},
                timeout=TIMEOUT
            )
            # Логирование статуса и тела ответа для отладки
            logger.info(f"Получен ответ: HTTP {response.status_code}")
            logger.info(f"Тело ответа: {response.text}")

            response.raise_for_status()  # Проверка успешности запроса

            # Преобразование ответа в JSON
            data = response.json()
            if not data:
                break

            # Параллельное клонирование проектов
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for project in data:
                    executor.submit(clone_project, project, path)

            page += 1
        except requests.RequestException as e:
            logger.error(f"Ошибка при получении проектов группы {group_id}: {e}")
            break
        except ValueError:
            logger.error("Ошибка декодирования JSON. Возможно, ответ от сервера не является корректным JSON.")
            break

    # Получаем подгруппы и рекурсивно обрабатываем их
    try:
        subgroups_response = requests.get(
            f"{GITLAB_URL}/api/v4/groups/{group_id}/subgroups",
            headers={"PRIVATE-TOKEN": access_token},
            timeout=TIMEOUT
        )
        logger.info(f"Получен ответ для подгрупп: HTTP {subgroups_response.status_code}")
        logger.info(f"Тело ответа для подгрупп: {subgroups_response.text}")

        subgroups_response.raise_for_status()  # Проверка успешности запроса
        subgroups = subgroups_response.json()
    except requests.RequestException as e:
        logger.error(f"Ошибка при получении подгрупп группы {group_id}: {e}")
        subgroups = []
    except ValueError:
        logger.error("Ошибка декодирования JSON при получении подгрупп.")
        subgroups = []

    # Рекурсивно клонируем проекты из каждой подгруппы
    for subgroup in subgroups:
        subgroup_path = os.path.join(path, slugify_project_name(subgroup['name']))
        if not os.path.exists(subgroup_path):
            os.makedirs(subgroup_path)
        get_projects(subgroup['id'], access_token, subgroup_path)


# Создание корневой директории для группы
root_path = os.path.join(os.getcwd(), slugify_project_name(GROUP_ID))
if not os.path.exists(root_path):
    os.makedirs(root_path)

# Получение и клонирование всех проектов
get_projects(GROUP_ID, ACCESS_TOKEN, root_path)

