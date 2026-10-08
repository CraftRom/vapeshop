"""Read Telegram product images without exposing bot credentials."""
async def telegram_product_photo(bot, file_id):
    info = await bot.get_file(file_id)
    content = await bot.download_file(info.file_path)
    return content.read() if hasattr(content, 'read') else content
