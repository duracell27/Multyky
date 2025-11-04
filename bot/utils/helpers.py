import os
import tempfile
import subprocess
from aiogram import Bot
from aiogram.types import Message, FSInputFile


async def send_movie_video(bot: Bot, chat_id: int, movie: dict, caption: str = None) -> Message:
    """
    Відправляє відео мультфільма користувачу
    Автоматично визначає чи це video чи document і використовує правильний метод

    Args:
        bot: Екземпляр бота
        chat_id: ID чату куди відправити
        movie: Словник з даними мультфільма (має містити video_file_id та video_type)
        caption: Опціональний підпис до відео

    Returns:
        Message: Відправлене повідомлення
    """
    video_file_id = movie.get("video_file_id")
    video_type = movie.get("video_type", "video")  # За замовчуванням video

    if video_type == "video":
        # Відправляємо як звичайне відео
        return await bot.send_video(
            chat_id=chat_id,
            video=video_file_id,
            caption=caption
        )
    else:
        # Відправляємо як document, але користувач зможе його переглянути
        return await bot.send_document(
            chat_id=chat_id,
            document=video_file_id,
            caption=caption
        )


async def convert_video_to_mp4(bot: Bot, file_id: str, original_filename: str = None) -> tuple[str, str]:
    """
    Конвертує відео в MP4 формат (h264 codec) для кращої сумісності

    Args:
        bot: Екземпляр бота
        file_id: File ID відео в Telegram
        original_filename: Оригінальна назва файлу

    Returns:
        tuple: (шлях до конвертованого файлу, новий file_id)
    """
    # Створюємо тимчасові директорії
    temp_dir = tempfile.mkdtemp()

    try:
        # Завантажуємо файл
        file = await bot.get_file(file_id)
        original_path = os.path.join(temp_dir, original_filename or "original.mkv")
        await bot.download_file(file.file_path, original_path)

        # Конвертуємо в MP4
        output_path = os.path.join(temp_dir, "converted.mp4")

        # Використовуємо ffmpeg для конвертації
        # -c:v libx264 - відео кодек h264
        # -c:a aac - аудіо кодек aac
        # -movflags +faststart - оптимізація для стрімінгу
        # -preset medium - баланс між швидкістю і якістю
        command = [
            "ffmpeg",
            "-i", original_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "medium",
            "-movflags", "+faststart",
            "-y",  # Перезаписати якщо існує
            output_path
        ]

        # Запускаємо конвертацію
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600  # 10 хвилин максимум
        )

        if process.returncode != 0:
            raise Exception(f"FFmpeg error: {process.stderr.decode()}")

        return output_path, temp_dir

    except Exception as e:
        # Видаляємо тимчасові файли при помилці
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise e


def cleanup_temp_files(temp_dir: str):
    """Видаляє тимчасові файли"""
    import shutil
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except:
        pass
