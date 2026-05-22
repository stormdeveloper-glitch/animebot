async def safe_tool_call(tool_func, message):
    try:
        await tool_func(message)

    except Exception as e:
        try:
            await message.answer("❌ Xatolik yuz berdi, qayta urinib ko‘r")
        except:
            pass
          
