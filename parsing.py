import io
import logging
from typing import Any

import hikari
from aiohttp import ClientSession

logger = logging.getLogger(__name__)

rest_app = hikari.RESTApp()

latest_rpt_log_file_name = None
parsed_rpt_log_file_lines = []


async def download_latest_rpg_logfile(
    service_id: int, access_token: str
) -> io.BytesIO | None:
    async with ClientSession() as session:
        headers = {"Authorization": f"Bearer {access_token}"}

        async with session.get(
            f"https://api.nitrado.net/services/{service_id}/gameservers",
            headers=headers,
        ) as service_info_response:
            if service_info_response.status != 200:
                logger.error(
                    f"Failed to fetch Service Information for {service_id}. Response Status: {service_info_response.status}, Text: {await service_info_response.text()}"
                )
                return None

            service_info_response_json = await service_info_response.json()

        nolog = (
            service_info_response_json["data"]["gameserver"]["settings"][
                "general"
            ]["nolog"]
            == "true"
        )
        if nolog:
            logger.error(
                f"Failed to parse RPT log for {service_id}. Reason: `Reduce Log Output` is enabled"
            )
            return None

        game = service_info_response_json["data"]["gameserver"]["game"]
        ftp_username = service_info_response_json["data"]["gameserver"][
            "username"
        ]

        async with session.get(
            f"https://api.nitrado.net/services/{service_id}/gameservers/file_server/list",
            headers=headers,
            json={"dir": f"/games/{ftp_username}/noftp/{game}/config"},
        ) as file_list_response:
            if file_list_response.status != 200:
                logger.error(
                    f"Failed to fetch File List for {service_id}. Response Status: {file_list_response.status}, Text: {await file_list_response.text()}"
                )
                return None

            file_list_response_json: dict[
                str, Any
            ] = await file_list_response.json()

        rpt_log_file_entries = [
            entry["name"]
            for entry in file_list_response_json["data"]["entries"]
            if ".RPT" in entry["name"]
        ]
        rpt_log_file_entries.sort()

        rpt_log_file_name = rpt_log_file_entries[-1]

        global latest_rpt_log_file_name
        if latest_rpt_log_file_name is None:
            latest_rpt_log_file_name = rpt_log_file_name

        if latest_rpt_log_file_name != rpt_log_file_name:
            global parsed_rpt_log_file_lines
            latest_rpt_log_file_name = rpt_log_file_name
            parsed_rpt_log_file_lines = []

        async with session.get(
            f"https://api.nitrado.net/services/{service_id}/gameservers/file_server/download",
            headers=headers,
            json={
                "file": f"/games/{ftp_username}/noftp/{game}/config/{rpt_log_file_name}"
            },
        ) as download_url_response:
            if download_url_response.status != 200:
                logger.error(
                    f"Failed to get File download link for {service_id}. Response Status: {download_url_response.status}, Text: {await download_url_response.text()}"
                )
                return None

            download_url_response_json: dict[
                str, Any
            ] = await download_url_response.json()

        download_url = download_url_response_json["data"]["token"]["url"]

        async with session.get(download_url) as download_response:
            if download_response.status != 200:
                logger.error(
                    f"Failed to download file with URL {download_url} for {service_id}. Response Status: {download_response.status}, Text: {await download_response.text()}"
                )
                return None

            download_response_bytes = await download_response.read()

        buffer = io.BytesIO(download_response_bytes)
        buffer.seek(0)
        return buffer


async def parse_rpt_logfile(
    service_id: int, access_token: str, webhook_url: str
) -> None:
    logger.info(f"Parsing RPT Log File for {service_id}")

    suspected_glitch_event_count = 0
    rpt_log_file_buffer = await download_latest_rpg_logfile(
        service_id, access_token
    )
    if not rpt_log_file_buffer:
        return
    embed_chunks = [[]]
    lines = [
        line.strip()
        for line in rpt_log_file_buffer.read().decode().splitlines()
        if "preloading" in line and line not in parsed_rpt_log_file_lines
    ]

    for line in lines:
        parsed_rpt_log_file_lines.append(line)
        time = line.split(" Login: Player ")[0].split(".")[0]
        player_name = line.split("Player ")[1].split(" (")[0]
        x, y, z = line.split(") preloading at: ")[1].split(",")[0].split(" ")

        if not float(y) < 0:
            continue

        suspected_glitch_event_count += 1
        embed = hikari.Embed(
            description=f"Suspected Under-Map-Glitch attempt.\nTime: {time}\nUser: ` {player_name} `\nLocation: **{x} / {z}**"
        )

        if (
            sum([embed.total_length() for embed in embed_chunks[-1]])
            + embed.total_length()
        ) <= 6000 and len(embed_chunks[-1]) < 10:
            embed_chunks[-1].append(embed)
        else:
            embed_chunks.append([embed])

    if not rest_app._client_session:
        await rest_app.start()

    async with rest_app.acquire() as rest_client:
        webhook_id, webhook_token = webhook_url.split("/")[-2:]
        for embed_list in embed_chunks:
            if not embed_list:
                continue

            await rest_client.execute_webhook(
                int(webhook_id), webhook_token, embeds=embed_list
            )

    logger.info(
        f"Finished parsing RPT Log File for {service_id}. Found {suspected_glitch_event_count} suspected glitch {'event' if suspected_glitch_event_count == 1 else 'events'}"
    )
