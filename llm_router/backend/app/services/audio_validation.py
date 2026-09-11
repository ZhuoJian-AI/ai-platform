"""Decode provider audio consistently for capability verification and delivery."""

import asyncio


async def validate_audio_output(raw: bytes, output_format: str) -> str:
    if not raw:
        raise ValueError("语音模型返回了空文件")
    if output_format == "wav":
        if len(raw) < 12 or not raw.startswith(b"RIFF") or raw[8:12] != b"WAVE":
            raise ValueError("语音模型返回的内容不是有效 WAV 文件")
    elif output_format == "mp3":
        is_id3 = raw.startswith(b"ID3")
        is_frame = len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0
        if not (is_id3 or is_frame):
            raise ValueError("语音模型返回的内容不是有效 MP3 文件")
    else:
        raise ValueError("不支持的语音输出格式")
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1",
        "-protocol_whitelist", "pipe", "-f", output_format, "-i", "pipe:0",
        "-map", "0:a:0", "-progress", "pipe:1", "-f", "null", "-",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        progress, _ = await asyncio.wait_for(process.communicate(raw), timeout=30)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    decoded = any(
        line.startswith(b"out_time_us=") and line.partition(b"=")[2].isdigit()
        and int(line.partition(b"=")[2]) > 0
        for line in progress.splitlines()
    )
    if process.returncode != 0 or not decoded:
        raise ValueError("语音文件无法完整解码或没有有效音频")
    return "audio/wav" if output_format == "wav" else "audio/mpeg"
