import asyncio
import io
import re
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

try:
    import pytesseract
    from PIL import Image

    # O Tesseract está instalado no Windows, mas não está no PATH.
    # Apontamos diretamente para o executável para o bot funcionar
    # mesmo que "tesseract" não seja reconhecido no PowerShell.
    TESSERACT_EXE = os.path.join(r"C:\Program Files\Tesseract-OCR", "tesseract.exe")
    if os.path.exists(TESSERACT_EXE):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
    else:
        TESSERACT_EXE = None
except ImportError:
    pytesseract = None
    Image = None
    TESSERACT_EXE = None


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN or TOKEN == "COLE_SEU_TOKEN_AQUI":
    raise RuntimeError(
        "Token do Discord não configurado no arquivo .env."
    )


DEFAULT_CONFIG = {
    "guild_id": 1543687489422889090,

    "support_role_id": 1543697270677962753,
    "preparador_role_id": 1543697269893894325,
    "manager_role_id": 1543717219916189727,
    "developer_role_id": 1548890509026529320,

    "logs_channel_id": 1543834911574720522,
    "tickets_open_channel_id": 1543834845304590376,
    "tickets_closed_channel_id": 1543834911574720522,

    "ticket_categories": {
        "suporte": 1543836548536074363,
        "acerto": 1543836179672203264,
        "pix": 1550344537774493746,
        "teste_preparador": 1543837115941519430,
        "drag": 1550570219825799189
    },

    # Categoria privada enquanto o comprovante Pix ainda não foi enviado.
    # Depois do envio, o ticket vai para esta categoria final.
    "pix_final_category_id": 1548089221820977173,

    "panel_channel_id": 1543697539927117884,
    "general_channel_id": 1543697522906636438,
    "panel_message_id": 0,

    "exceptional_open": False,
    "max_open_tickets": 10,

    "timezone": "America/Sao_Paulo",

    "business_hours": {
        "monday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ],
        "tuesday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ],
        "wednesday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ],
        "thursday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ],
        "friday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ],
        "saturday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ],
        "sunday": [
            ["10:00", "12:30"],
            ["13:30", "19:00"],
            ["21:00", "00:00"]
        ]
    }
}


# ============================================================
# CONFIG.JSON
# ============================================================

def save_config():
    CONFIG_FILE.write_text(
        json.dumps(
            config,
            indent=4,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


def load_config():
    if not CONFIG_FILE.exists():
        data = DEFAULT_CONFIG.copy()

        CONFIG_FILE.write_text(
            json.dumps(
                data,
                indent=4,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

        return data

    try:
        data = json.loads(
            CONFIG_FILE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        data = DEFAULT_CONFIG.copy()

    changed = False

    def merge(target, defaults):
        nonlocal changed

        for key, value in defaults.items():

            if key not in target:
                target[key] = value
                changed = True

            elif isinstance(value, dict) and isinstance(
                target[key],
                dict
            ):
                merge(target[key], value)

    merge(data, DEFAULT_CONFIG)

    if changed:
        CONFIG_FILE.write_text(
            json.dumps(
                data,
                indent=4,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

    return data


config = load_config()

# Garante que o estado excepcional seja realmente booleano.
# Isso impede que a string "False" seja interpretada como True.
if not isinstance(config.get("exceptional_open"), bool):
    config["exceptional_open"] = str(config.get("exceptional_open", "false")).strip().lower() in ("true", "1", "yes", "sim")
    save_config()

# A categoria inicial de Pix agora é a categoria privada de comprovantes.
# O canal é movido para a categoria final somente após o envio da imagem.
if config.get("ticket_categories", {}).get("pix") != 1550344537774493746:
    config["ticket_categories"]["pix"] = 1550344537774493746
    save_config()

if config.get("pix_final_category_id") != 1548089221820977173:
    config["pix_final_category_id"] = 1548089221820977173
    save_config()


# ============================================================
# HORÁRIO
# ============================================================

try:
    TZ = ZoneInfo(
        config.get(
            "timezone",
            "America/Sao_Paulo"
        )
    )
except Exception:
    TZ = ZoneInfo("America/Sao_Paulo")


def now_local():
    return datetime.now(TZ)


DAY_NAMES = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday"
}


def time_to_minutes(value):
    hour, minute = map(
        int,
        value.split(":")
    )

    return hour * 60 + minute


def is_inside_business_hours():
    current = now_local()

    day = DAY_NAMES[current.weekday()]

    periods = config.get(
        "business_hours",
        {}
    ).get(
        day,
        []
    )

    current_minutes = (
        current.hour * 60
        + current.minute
    )

    for start, end in periods:

        start_minutes = time_to_minutes(start)
        end_minutes = time_to_minutes(end)

        if end == "00:00":

            if current_minutes >= start_minutes:
                return True

        elif start_minutes <= current_minutes < end_minutes:
            return True

    return False


def atendimento_aberto():

    # Só abre excepcional quando o valor salvo for booleano True.
    # Nunca trata a string "False" como atendimento aberto.
    if config.get("exceptional_open") is True:
        return True

    return is_inside_business_hours()


def status_text():

    if config.get(
        "exceptional_open",
        False
    ):
        return "🟢 Atendimento aberto — excepcional"

    if is_inside_business_hours():
        return "🟢 Atendimento aberto"

    return "🔴 Atendimento encerrado"


# ============================================================
# TIPOS DE TICKET
# ============================================================

TICKET_TYPES = {

    "suporte": {
        "name": "Suporte",
        "emoji": "🛠️",
        "color": discord.Color.blurple(),
        "category": "suporte"
    },

    "acerto": {
        "name": "Acerto",
        "emoji": "💰",
        "color": discord.Color.gold(),
        "category": "acerto"
    },

    "pix": {
        "name": "Acertos Pix",
        "emoji": "💸",
        "color": discord.Color.green(),
        "category": "pix"
    },

    "teste_preparador": {
        "name": "Teste Preparador",
        "emoji": "🧪",
        "color": discord.Color.purple(),
        "category": "teste_preparador"
    },

    "drag": {
        "name": "Desafio de Drag",
        "emoji": "🏁",
        "color": discord.Color.orange(),
        "category": "drag"
    }
}


def ticket_type_name(ticket_type):

    data = TICKET_TYPES.get(
        ticket_type
    )

    if not data:
        return ticket_type

    return (
        f"{data['emoji']} "
        f"{data['name']}"
    )


# ============================================================
# PERMISSÕES
# ============================================================

def get_role(guild, role_id):

    if not guild:
        return None

    return guild.get_role(
        int(role_id)
    )


def is_manager_or_above(member):

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    if member.guild_permissions.administrator:
        return True

    manager_role = get_role(
        member.guild,
        config["manager_role_id"]
    )

    if not manager_role:
        return False

    return (
        member.top_role.position
        >= manager_role.position
    )


def has_role(member, role_id):

    if not isinstance(
        member,
        discord.Member
    ):
        return False

    return any(
        role.id == int(role_id)
        for role in member.roles
    )


def can_manage_ticket(
    member,
    ticket_type
):

    if is_manager_or_above(member):
        return True

    if ticket_type == "suporte":

        return has_role(
            member,
            config["support_role_id"]
        )

    if ticket_type in (
        "acerto",
        "teste_preparador"
    ):

        return has_role(
            member,
            config["preparador_role_id"]
        )

    if ticket_type == "drag":
        return is_manager_or_above(member)

    return False


# ============================================================
# TOPIC DO TICKET
# ============================================================

def make_topic(
    owner_id, ticket_type, claimed=0, created=None, payment=None, pix_status="pending"
):
    if created is None:
        created = now_local().isoformat()
    topic = (
        "GTC_TICKET|"
        f"owner={owner_id}|"
        f"type={ticket_type}|"
        f"claimed={claimed}|"
        f"created={created}|"
        f"pix_status={pix_status}"
    )
    if payment:
        topic += f"|payment={payment}"
    return topic


def parse_topic(topic):

    if not topic:
        return None

    if not topic.startswith(
        "GTC_TICKET|"
    ):
        return None

    data = {}

    for part in topic.split("|")[1:]:

        if "=" not in part:
            continue

        key, value = part.split(
            "=",
            1
        )

        data[key] = value

    if (
        "owner" not in data
        or "type" not in data
    ):
        return None

    try:

        data["owner"] = int(
            data["owner"]
        )

        data["claimed"] = int(
            data.get(
                "claimed",
                0
            )
        )

    except ValueError:
        return None

    return data


async def update_topic(channel, data):
    await channel.edit(
        topic=make_topic(
            data["owner"], data["type"], data.get("claimed", 0),
            data.get("created"), data.get("payment"), data.get("pix_status", "pending")
        )
    )


# ============================================================
# TICKETS ABERTOS
# ============================================================

def get_ticket_channels(guild):

    return [
        channel
        for channel in guild.text_channels
        if parse_topic(channel.topic)
    ]


def count_open_tickets(guild):

    return len(
        get_ticket_channels(guild)
    )


def user_has_open_ticket(
    guild,
    user_id
):

    for channel in get_ticket_channels(guild):

        data = parse_topic(
            channel.topic
        )

        if (
            data
            and (
                data["owner"] == user_id
                or int(data.get("opponent", 0) or 0) == user_id
            )
        ):
            return True

    return False


# ============================================================
# LOG
# ============================================================

async def send_log(
    guild,
    title,
    description,
    color=discord.Color.blurple(),
    file_path=None
):

    channel = guild.get_channel(
        int(
            config.get(
                "logs_channel_id",
                0
            )
        )
    )

    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=now_local()
    )

    try:

        if (
            file_path
            and file_path.exists()
        ):

            await channel.send(
                embed=embed,
                file=discord.File(
                    str(file_path),
                    filename=file_path.name
                )
            )

        else:
            await channel.send(
                embed=embed
            )

    except Exception as error:

        print(
            f"[LOG] {error}"
        )


# ============================================================
# TRANSCRIPT
# ============================================================

async def generate_transcript(
    channel
):

    data = parse_topic(
        channel.topic
    )

    lines = []

    lines.append(
        "=" * 70
    )

    lines.append(
        "GTC PERFORMANCE - TRANSCRIPT"
    )

    lines.append(
        "=" * 70
    )

    lines.append(
        f"Canal: {channel.name}"
    )

    lines.append(
        f"Gerado em: "
        f"{now_local().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    if data:

        lines.append(
            f"ID do membro: {data['owner']}"
        )

        lines.append(
            f"Tipo: "
            f"{ticket_type_name(data['type'])}"
        )

        if data.get(
            "claimed",
            0
        ):

            lines.append(
                f"Responsável: "
                f"{data['claimed']}"
            )

        lines.append(
            f"Criado em: "
            f"{data.get('created', 'N/A')}"
        )

    lines.append("")
    lines.append(
        "=" * 70
    )
    lines.append(
        "MENSAGENS"
    )
    lines.append(
        "=" * 70
    )

    try:

        messages = [
            message
            async for message
            in channel.history(
                limit=None,
                oldest_first=True
            )
        ]

    except Exception as error:

        messages = []

        lines.append(
            f"Erro lendo mensagens: {error}"
        )

    for message in messages:

        timestamp = (
            message.created_at
            .astimezone(TZ)
            .strftime(
                "%d/%m/%Y %H:%M:%S"
            )
        )

        lines.append(
            f"[{timestamp}] "
            f"{message.author} "
            f"({message.author.id}):"
        )

        if message.content:
            lines.append(
                message.content
            )

        if message.attachments:

            lines.append(
                "Anexos:"
            )

            for attachment in message.attachments:

                lines.append(
                    f"- {attachment.url}"
                )

        lines.append("")

    lines.append(
        "=" * 70
    )

    lines.append(
        "FIM DO TRANSCRIPT"
    )

    lines.append(
        "=" * 70
    )

    content = "\n".join(
        lines
    )

    safe_name = re.sub(
        r"[^a-zA-Z0-9_-]",
        "_",
        channel.name
    )

    filepath = (
        BASE_DIR
        / f"transcript-{safe_name}-"
        f"{now_local().strftime('%Y%m%d-%H%M%S')}.txt"
    )

    filepath.write_text(
        content,
        encoding="utf-8"
    )

    return filepath


# ============================================================
# DM DO USUÁRIO
# ============================================================

async def send_transcript_dm(
    user_id,
    filepath,
    reason
):

    try:

        user = await bot.fetch_user(
            int(user_id)
        )

        embed = discord.Embed(
            title="🔒 Ticket encerrado",
            description=(
                "Seu ticket foi encerrado.\n\n"
                f"**Motivo:** {reason}"
            ),
            color=discord.Color.red(),
            timestamp=now_local()
        )

        await user.send(
            embed=embed,
            file=discord.File(
                str(filepath),
                filename=filepath.name
            )
        )

    except discord.Forbidden:
        print(f"[DM] Não foi possível enviar o transcript por DM para o usuário {user_id}.")
    except discord.NotFound:
        print(f"[DM] Usuário {user_id} não encontrado.")
    except Exception as error:

        print(
            f"[DM] {error}"
        )


# ============================================================
# FECHAMENTO
# ============================================================

closing_tickets = set()


async def close_ticket(
    channel,
    closer,
    reason,
    automatic=False
):

    if channel.id in closing_tickets:
        return

    closing_tickets.add(
        channel.id
    )
    cancel_pix_receipt_task(channel.id)

    try:

        guild = channel.guild

        data = parse_topic(
            channel.topic
        )

        if not data:
            return

        if data.get("type") == "drag":
            delete_drag_data(channel.id)

        filepath = (
            await generate_transcript(
                channel
            )
        )

        await send_transcript_dm(
            data["owner"],
            filepath,
            reason
        )

        title = (
            "🤖 Ticket fechado automaticamente"
            if automatic
            else "🔒 Ticket fechado"
        )

        claimed = data.get(
            "claimed",
            0
        )

        description = (
            f"**Tipo:** "
            f"{ticket_type_name(data['type'])}\n"
            f"**Membro:** <@{data['owner']}>\n"
            f"**Responsável:** "
            f"{f'<@{claimed}>' if claimed else 'Ninguém'}\n"
            f"**Fechado por:** "
            f"{closer.mention if closer else 'Sistema automático'}\n"
            f"**Motivo:** {reason}\n"
            f"**Canal:** `{channel.name}`"
        )

        await send_log(
            guild,
            title,
            description,
            discord.Color.red(),
            filepath
        )

        await asyncio.sleep(1)

        try:
            filepath.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        try:
            await channel.delete(
                reason=reason
            )
        except discord.NotFound:
            # Outro processo pode ter apagado o canal antes deste task.
            print(f"[CLOSE] Canal {channel.id} já não existe.")
        except discord.Forbidden:
            print(f"[CLOSE] Sem permissão para apagar o canal {channel.id}.")
        except Exception as error:
            print(f"[CLOSE] Erro ao apagar canal: {error}")

    except discord.NotFound:
        print(f"[CLOSE] Canal {getattr(channel, 'id', 'desconhecido')} não encontrado.")
    except Exception as error:

        print(
            f"[CLOSE] {error}"
        )

    finally:

        closing_tickets.discard(
            channel.id
        )


# ============================================================
# MODAL DE FECHAMENTO
# ============================================================

class CloseTicketModal(
    discord.ui.Modal,
    title="🔒 Fechar Ticket"
):

    motivo = discord.ui.TextInput(
        label="Motivo do fechamento",
        placeholder="Digite o motivo do fechamento...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=3,
        max_length=500
    )

    def __init__(self, channel):

        super().__init__()

        self.channel = channel

    async def on_submit(
        self,
        interaction
    ):

        data = parse_topic(
            self.channel.topic
        )

        if not data:

            await interaction.response.send_message(
                "❌ Este canal não é um ticket.",
                ephemeral=True
            )

            return

        if not can_manage_ticket(
            interaction.user,
            data["type"]
        ):

            await interaction.response.send_message(
                "❌ Você não tem permissão para fechar este ticket.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🔒 Fechando ticket e gerando transcript...",
            ephemeral=True
        )

        await close_ticket(
            self.channel,
            interaction.user,
            str(self.motivo.value)
        )


# ============================================================
# MODAL DE SUPORTE
# ============================================================

class SuporteModal(
    discord.ui.Modal,
    title="🛠️ Suporte"
):

    motivo = discord.ui.TextInput(
        label="Por que você precisa de suporte?",
        placeholder="Explique o que aconteceu...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=3,
        max_length=1000
    )

    def __init__(self, user_id):

        super().__init__()

        self.user_id = user_id

    async def on_submit(
        self,
        interaction
    ):

        await create_ticket(
            interaction,
            "suporte",
            {
                "motivo": str(
                    self.motivo.value
                )
            }
        )


# ============================================================
# MODAL DE TESTE PREPARADOR
# ============================================================

class TestePreparadorModal(
    discord.ui.Modal,
    title="🧪 Teste Preparador"
):

    etanol = discord.ui.TextInput(
        label="Você sabe acertar carro no etanol?",
        placeholder="Sim / Não / Explique...",
        required=True,
        max_length=500
    )

    nitrometano = discord.ui.TextInput(
        label="Sabe acertar carro no nitrometano?",
        placeholder="Sim / Não / Explique...",
        required=True,
        max_length=500
    )

    def __init__(self, user_id):

        super().__init__()

        self.user_id = user_id

    async def on_submit(
        self,
        interaction
    ):

        await create_ticket(
            interaction,
            "teste_preparador",
            {
                "etanol": str(
                    self.etanol.value
                ),
                "nitrometano": str(
                    self.nitrometano.value
                )
            }
        )


# ============================================================
# MODAL DO CARRO
# ============================================================

class CarModal(
    discord.ui.Modal,
    title="🚗 Informar carro"
):

    carro = discord.ui.TextInput(
        label="Qual é o carro?",
        placeholder="Exemplo: BMW M3 G80",
        required=True,
        max_length=100
    )

    def __init__(
        self,
        ticket_type
    ):

        super().__init__()

        self.ticket_type = ticket_type

    async def on_submit(
        self,
        interaction
    ):

        if self.ticket_type == "pix":

            await interaction.response.send_message(
                "🚗 Carro recebido. Agora escolha a forma de pagamento:",
                ephemeral=True,
                view=PixPaymentView(
                    str(self.carro.value)
                )
            )

        else:

            await interaction.response.send_message(
                "🚗 Carro recebido. Agora escolha a forma de pagamento:",
                ephemeral=True,
                view=AcertoPaymentView(
                    str(self.carro.value)
                )
            )


# ============================================================
# PAGAMENTO PIX
# ============================================================

class PixPaymentSelect(
    discord.ui.Select
):

    def __init__(self, carro):

        self.carro = carro

        options = [

            discord.SelectOption(
                label="Compensações zeradas - R$ 3,47",
                description="Compensação zerada",
                value="Compensações zeradas - R$ 3,47"
            ),

            discord.SelectOption(
                label="Compensações sem zerar (originais) - R$ 4,45",
                description="Compensação original",
                value="Compensações sem zerar (originais) - R$ 4,45"
            )
        ]

        super().__init__(
            placeholder="💳 Escolha a forma de pagamento...",
            options=options,
            custom_id="gtc:pix:payment"
        )

    async def callback(
        self,
        interaction
    ):

        await interaction.response.edit_message(
            content=(
                "✅ Dados preenchidos!\n\n"
                f"**Carro:** {self.carro}\n"
                f"**Pagamento:** {self.values[0]}\n\n"
                "Clique abaixo para criar o ticket."
            ),
            view=PixCreateView(
                self.carro,
                self.values[0]
            )
        )


class PixPaymentView(
    discord.ui.View
):

    def __init__(self, carro):

        super().__init__(
            timeout=300
        )

        self.add_item(
            PixPaymentSelect(
                carro
            )
        )


class PixCreateView(
    discord.ui.View
):

    def __init__(
        self,
        carro,
        payment
    ):

        super().__init__(
            timeout=300
        )

        self.carro = carro
        self.payment = payment

    @discord.ui.button(
        label="Criar Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.success,
        custom_id="gtc:pix:create"
    )
    async def create(
        self,
        interaction,
        button
    ):

        await create_ticket(
            interaction,
            "pix",
            {
                "carro": self.carro,
                "payment": self.payment
            }
        )


# ============================================================
# ACERTO NORMAL
# ============================================================

class AcertoPaymentSelect(
    discord.ui.Select
):

    def __init__(self, carro):

        self.carro = carro

        options = [

            discord.SelectOption(
                label="Compensações zeradas - 100k",
                description="Compensação zerada",
                value="Compensações zeradas - 100k"
            ),

            discord.SelectOption(
                label="Compensações originais - 170k",
                description="Compensação original",
                value="Compensações originais - 170k"
            )
        ]

        super().__init__(
            placeholder="💳 Escolha a forma de pagamento...",
            options=options,
            custom_id="gtc:acerto:payment"
        )

    async def callback(
        self,
        interaction
    ):

        await interaction.response.edit_message(
            content=(
                "✅ Dados preenchidos!\n\n"
                f"**Carro:** {self.carro}\n"
                f"**Pagamento:** {self.values[0]}\n\n"
                "Clique abaixo para criar o ticket."
            ),
            view=AcertoCreateView(
                self.carro,
                self.values[0]
            )
        )


class AcertoPaymentView(
    discord.ui.View
):

    def __init__(
        self,
        carro
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            AcertoPaymentSelect(
                carro
            )
        )


class AcertoCreateView(
    discord.ui.View
):

    def __init__(
        self,
        carro,
        payment
    ):

        super().__init__(
            timeout=300
        )

        self.carro = carro
        self.payment = payment

    @discord.ui.button(
        label="Criar Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.success,
        custom_id="gtc:acerto:create"
    )
    async def create(
        self,
        interaction,
        button
    ):

        await create_ticket(
            interaction,
            "acerto",
            {
                "carro": self.carro,
                "payment": self.payment
            }
        )


# ============================================================
# BOTÕES DOS TICKETS
# ============================================================

class TicketControlView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="Assumir Ticket",
        emoji="👮",
        style=discord.ButtonStyle.primary,
        custom_id="gtc:ticket:claim"
    )
    async def claim(
        self,
        interaction,
        button
    ):

        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel

        data = parse_topic(
            channel.topic
        )

        if not data:

            await interaction.followup.send(
                "❌ Este canal não é um ticket.",
                ephemeral=True
            )

            return

        if not can_manage_ticket(
            interaction.user,
            data["type"]
        ):

            await interaction.followup.send(
                "❌ Você não tem permissão para assumir este ticket.",
                ephemeral=True
            )

            return

        if data.get(
            "claimed",
            0
        ) == interaction.user.id:

            await interaction.followup.send(
                "⚠️ Você já assumiu este ticket.",
                ephemeral=True
            )

            return

        data["claimed"] = (
            interaction.user.id
        )

        await update_topic(
            channel,
            data
        )

        await channel.send(
            embed=discord.Embed(
                title="👮 Ticket assumido",
                description=(
                    f"Este ticket foi assumido por "
                    f"{interaction.user.mention}."
                ),
                color=discord.Color.blue(),
                timestamp=now_local()
            )
        )

        await send_log(
            interaction.guild,
            "👮 Ticket assumido",
            (
                f"**Tipo:** "
                f"{ticket_type_name(data['type'])}\n"
                f"**Membro:** <@{data['owner']}>\n"
                f"**Responsável:** "
                f"{interaction.user.mention}\n"
                f"**Canal:** `{channel.name}`"
            ),
            discord.Color.blue()
        )

        await interaction.followup.send(
            "✅ Ticket assumido com sucesso.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Fechar Ticket",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="gtc:ticket:close"
    )
    async def close(
        self,
        interaction,
        button
    ):

        channel = interaction.channel

        data = parse_topic(
            channel.topic
        )

        if not data:

            await interaction.response.send_message(
                "❌ Este canal não é um ticket.",
                ephemeral=True
            )

            return

        if not can_manage_ticket(
            interaction.user,
            data["type"]
        ):

            await interaction.response.send_message(
                "❌ Você não tem permissão para fechar este ticket.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            CloseTicketModal(
                channel
            )
        )


# ============================================================
# CRIAÇÃO DO TICKET
# ============================================================



# ============================================================
# VERIFICAÇÃO AUTOMÁTICA DE COMPROVANTE PIX
# ============================================================

async def verificar_comprovante_pix(message):
    """Analisa imagens Pix e classifica como comprovante, ilegivel, nao_comprovante ou suspeito."""
    if pytesseract is None or Image is None:
        return {
            "status": "indisponivel",
            "reason": "pytesseract/Pillow não instalados"
        }

    if not TESSERACT_EXE or not os.path.exists(TESSERACT_EXE):
        return {
            "status": "indisponivel",
            "reason": "Executável do Tesseract não encontrado em C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        }

    for attachment in message.attachments:
        content_type = (attachment.content_type or "").lower()
        filename = attachment.filename.lower()
        if not (
            content_type.startswith("image/")
            or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))
        ):
            continue

        try:
            data = await attachment.read()
            image = Image.open(io.BytesIO(data)).convert("RGB")

            # Garante que o pytesseract use o executável instalado no Windows.
            if TESSERACT_EXE:
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

            # Aumenta imagens pequenas para melhorar a leitura do Tesseract.
            if image.width < 1400:
                scale = 1400 / image.width
                image = image.resize(
                    (int(image.width * scale), int(image.height * scale))
                )

            texts = []
            configs = ("--psm 6", "--psm 11")
            languages = ("por+eng", "por", "eng")

            for lang in languages:
                try:
                    for tesseract_config in configs:
                        text_ocr = pytesseract.image_to_string(
                            image,
                            lang=lang,
                            config=tesseract_config
                        )
                        if text_ocr:
                            texts.append(text_ocr)
                    if texts:
                        break
                except Exception as ocr_error:
                    print(
                        f"[PIX OCR] Falha com idioma {lang}: {ocr_error}"
                    )

            text_ocr = "\n".join(texts)
            normalized = re.sub(
                r"\s+",
                " ",
                text_ocr.lower()
            ).strip()

            if len(normalized) < 12:
                return {
                    "status": "ilegivel",
                    "attachment": attachment,
                    "text": normalized
                }

            keywords = (
                "pix", "comprovante", "pagamento", "transferência",
                "transferencia", "valor", "r$", "recebedor", "favorecido",
                "enviado", "destinatário", "destinatario", "transação",
                "transacao", "instituição", "instituicao", "conta", "agência",
                "agencia", "data", "horário", "horario", "id da transação",
                "id da transacao", "autenticação", "autenticacao"
            )
            hits = sum(
                1 for keyword in keywords
                if keyword in normalized
            )

            receipt_header = (
                "comprovante" in normalized
                and any(
                    word in normalized
                    for word in (
                        "transferência",
                        "transferencia",
                        "pagamento",
                        "pix"
                    )
                )
            )

            transaction_signals = sum(
                1 for keyword in (
                    "valor", "recebedor", "favorecido", "destinatário",
                    "destinatario", "data", "horário", "horario", "id da transação",
                    "id da transacao", "instituição", "instituicao", "conta",
                    "agência", "agencia", "chave pix"
                )
                if keyword in normalized
            )

            # OCR pode errar o nome do recebedor. Por isso, o nome esperado
            # é usado como sinal forte, mas não é obrigatório para reconhecer
            # um comprovante que tenha estrutura clara de transferência.
            recipient_patterns = (
                "deivid almeida brites",
                "deivid almeida",
                "deivid",
                "brites"
            )
            has_recipient = (
                "deivid almeida brites" in normalized
                or (
                    "deivid" in normalized
                    and "brites" in normalized
                )
            )

            pix_words = any(
                x in normalized
                for x in (
                    "pix",
                    "comprovante",
                    "pagamento",
                    "transferência",
                    "transferencia"
                )
            )

            # Comprovante claro: cabeçalho + sinais de transação.
            if receipt_header and transaction_signals >= 1:
                return {
                    "status": "comprovante",
                    "attachment": attachment,
                    "score": hits,
                    "has_recipient": has_recipient,
                    "text": normalized
                }

            # Também aceita comprovantes Pix em layouts diferentes.
            if pix_words and hits >= 3:
                return {
                    "status": "comprovante",
                    "attachment": attachment,
                    "score": hits,
                    "has_recipient": has_recipient,
                    "text": normalized
                }

            # Caso a imagem tenha sinais de Pix, mas não estrutura suficiente,
            # envia para conferência da Gerência em vez de acusar fraude.
            if pix_words and hits >= 2:
                return {
                    "status": "suspeito",
                    "attachment": attachment,
                    "score": hits,
                    "has_recipient": has_recipient,
                    "text": normalized
                }

            return {
                "status": "nao_comprovante",
                "attachment": attachment,
                "score": hits,
                "has_recipient": has_recipient,
                "text": normalized
            }

        except Exception as error:
            print(
                f"[PIX OCR] Erro em {attachment.filename}: {error}"
            )

    return {
        "status": "nao_comprovante",
        "attachment": None,
        "score": 0,
        "has_recipient": False,
        "text": ""
    }


async def create_ticket(
    interaction,
    ticket_type,
    extra
):

    guild = interaction.guild

    if not guild:

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "❌ Isso só funciona dentro do servidor.",
                ephemeral=True
            )

        return

    # --------------------------------------------------------
    # HORÁRIO
    # --------------------------------------------------------

    if not atendimento_aberto():

        if not interaction.response.is_done():

            await interaction.response.send_message(
                "🔴 O atendimento está encerrado no momento.",
                ephemeral=True
            )

        else:

            await interaction.followup.send(
                "🔴 O atendimento está encerrado no momento.",
                ephemeral=True
            )

        return

    # --------------------------------------------------------
    # LIMITE
    # --------------------------------------------------------

    current = count_open_tickets(
        guild
    )

    maximum = int(
        config.get(
            "max_open_tickets",
            10
        )
    )

    if (
        ticket_type != "pix"
        and maximum > 0
        and current >= maximum
    ):

        message = (
            f"❌ O limite de tickets foi atingido: "
            f"**{current}/{maximum}**."
        )

        if not interaction.response.is_done():
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                message,
                ephemeral=True
            )

        return

    # --------------------------------------------------------
    # UM TICKET POR USUÁRIO
    # --------------------------------------------------------

    if user_has_open_ticket(
        guild,
        interaction.user.id
    ):

        message = (
            "❌ Você já possui um ticket aberto."
        )

        if not interaction.response.is_done():
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                message,
                ephemeral=True
            )

        return

    info = TICKET_TYPES[
        ticket_type
    ]

    category_id = config[
        "ticket_categories"
    ].get(
        info["category"],
        0
    )

    category = guild.get_channel(
        int(category_id)
    )

    if not isinstance(
        category,
        discord.CategoryChannel
    ):

        message = (
            "❌ A categoria deste ticket não está configurada."
        )

        if not interaction.response.is_done():
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                message,
                ephemeral=True
            )

        return

    if not interaction.response.is_done():

        await interaction.response.defer(
            ephemeral=True
        )

    # --------------------------------------------------------
    # PERMISSÕES
    # --------------------------------------------------------

    overwrites = {

        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False
            ),

        interaction.user:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )
    }

    support_role = get_role(
        guild,
        config["support_role_id"]
    )

    preparador_role = get_role(
        guild,
        config["preparador_role_id"]
    )

    manager_role = get_role(
        guild,
        config["manager_role_id"]
    )
    developer_role = get_role(
        guild,
        config.get("developer_role_id", 0)
    )

    if (
        ticket_type == "suporte"
        and support_role
    ):

        overwrites[support_role] = (
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )
        )

    if (
        ticket_type in (
            "acerto",
            "teste_preparador"
        )
        and preparador_role
    ):

        overwrites[preparador_role] = (
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )
        )

    developer_role = get_role(guild, config.get("developer_role_id", 0))

    # Tickets Pix ficam invisíveis para a Gerência até o bot detectar
    # um possível comprovante. A permissão explícita no canal sobrescreve
    # a permissão herdada da categoria.
    if ticket_type == "pix":
        # Na categoria privada de comprovantes, nenhum cargo de atendimento
        # abaixo da Gerência recebe acesso. O Developer é a exceção.
        for restricted_role in (manager_role, support_role, preparador_role):
            if restricted_role:
                overwrites[restricted_role] = discord.PermissionOverwrite(
                    view_channel=False,
                    send_messages=False,
                    read_message_history=False,
                    attach_files=False,
                    embed_links=False
                )

    if ticket_type != "pix" and manager_role:
        overwrites[manager_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True
        )

    if ticket_type == "pix" and developer_role:
        overwrites[developer_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            attach_files=True, embed_links=True
        )

    me = guild.me

    if me:

        overwrites[me] = (
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True
            )
        )

    # --------------------------------------------------------
    # NOME
    # --------------------------------------------------------

    username = re.sub(
        r"[^a-z0-9-]",
        "-",
        interaction.user.name.lower()
    )[:20]

    channel_name = (
        f"{info['emoji']}-{username}"
    )

    # --------------------------------------------------------
    # CRIA CANAL
    # --------------------------------------------------------

    created = now_local().isoformat()

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=make_topic(
            interaction.user.id,
            ticket_type,
            0,
            created,
            extra.get("payment"),
            "pending"
        ),
        reason=(
            f"Ticket aberto por "
            f"{interaction.user}"
        )
    )

    # --------------------------------------------------------
    # EMBED
    # --------------------------------------------------------

    embed = discord.Embed(
        title=(
            f"{info['emoji']} "
            f"{info['name']}"
        ),
        description=(
            f"Olá {interaction.user.mention}! 👋\n\n"
            "Seu ticket foi aberto.\n\n"
            f"**Tipo:** {info['name']}\n"
            f"**Atendimento:** {status_text()}"
        ),
        color=info["color"],
        timestamp=now_local()
    )

    # --------------------------------------------------------
    # INFORMAÇÕES ESPECÍFICAS
    # --------------------------------------------------------

    if ticket_type == "suporte":

        embed.add_field(
            name="📝 Motivo",
            value=extra.get(
                "motivo",
                "Não informado"
            ),
            inline=False
        )

    elif ticket_type in (
        "acerto",
        "pix"
    ):

        embed.add_field(
            name="🚗 Carro",
            value=extra.get(
                "carro",
                "Não informado"
            ),
            inline=True
        )

        embed.add_field(
            name="💳 Pagamento",
            value=extra.get(
                "payment",
                "Não informado"
            ),
            inline=True
        )

        if ticket_type == "pix":
            embed.add_field(
                name="⚠️ COMO ENVIAR O COMPROVANTE",
                value="Envie o comprovante Pix completo e legível para a conferência.",
                inline=False
            )

            embed.add_field(
                name="📄 Comprovante",
                value="Envie o comprovante Pix **completo**.",
                inline=True
            )

            embed.add_field(
                name="🖼️ Imagem",
                value="Print **legível**, sem cortar informações.",
                inline=True
            )

            embed.add_field(
                name="🔎 Informações",
                value="Deixe visíveis os dados da transferência.",
                inline=True
            )

            embed.add_field(
                name="❌ Evite",
                value="Imagens aleatórias, cortadas ou de baixa qualidade.",
                inline=True
            )

            embed.add_field(
                name="⏱️ Prazo",
                value="Envie em até **10 minutos**.",
                inline=True
            )


    elif ticket_type == "teste_preparador":

        embed.add_field(
            name="🟢 Etanol",
            value=extra.get(
                "etanol",
                "Não informado"
            ),
            inline=False
        )

        embed.add_field(
            name="🧪 Nitrometano",
            value=extra.get(
                "nitrometano",
                "Não informado"
            ),
            inline=False
        )

    embed.set_footer(
        text="GTC Performance • Atendimento"
    )

    await channel.send(
        content=interaction.user.mention,
        embed=embed,
        view=TicketControlView()
    )

    # --------------------------------------------------------
    # MENSAGEM AUTOMÁTICA DO PIX
    # --------------------------------------------------------

    if ticket_type == "pix":

        await channel.send(
            content=(
                "Cliente "
                "<@&1543697452664623284> "
                "<@&1543697417940111413>\n\n"
                "**PAGAMENTO**\n\n"
                " **Chave PIX:** "
                "`6f6008dc-54b3-489d-80d5-12132163643c`\n"
                " **Nome:** Deivid Almeida Brites\n\n"
                " Após realizar o pagamento, "
                "**envie o comprovante aqui no ticket** "
                "para confirmarmos o pagamento.\n\n"
                " Assim que o pagamento for confirmado, "
                "daremos continuidade à sua preparação!"
            )
        )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    details = (
        f"**Tipo:** "
        f"{ticket_type_name(ticket_type)}\n"
        f"**Membro:** "
        f"{interaction.user.mention} "
        f"(`{interaction.user.id}`)\n"
        f"**Canal:** {channel.mention}\n"
        f"**Horário:** "
        f"{now_local().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    if ticket_type in (
        "acerto",
        "pix"
    ):

        details += (
            f"\n**Carro:** "
            f"{extra.get('carro', 'N/A')}\n"
            f"**Pagamento:** "
            f"{extra.get('payment', 'N/A')}"
        )

    if ticket_type == "suporte":

        details += (
            f"\n**Motivo:** "
            f"{extra.get('motivo', 'N/A')}"
        )

    if ticket_type == "teste_preparador":

        details += (
            f"\n**Etanol:** "
            f"{extra.get('etanol', 'N/A')}\n"
            f"**Nitrometano:** "
            f"{extra.get('nitrometano', 'N/A')}"
        )

    await send_log(
        guild,
        "🎫 Ticket aberto",
        details,
        info["color"]
    )

    await interaction.followup.send(
        f"✅ Ticket criado: {channel.mention}",
        ephemeral=True
    )

    schedule_inactivity(
        channel
    )

    if ticket_type == "pix":
        schedule_pix_receipt_timeout(channel)


# ============================================================
# DESAFIO DE DRAG
# ============================================================

DRAG_RULES = """🏁 **REGRAS — DESAFIO DE DRAG**

**FORMATO DA PARTIDA**
• O Drag será no formato **MD3 (Melhor de 3)**.
• São disputadas até 3 corridas.
• Quem ganhar **2 corridas primeiro** vence.
• Se um jogador ganhar as duas primeiras, a terceira não será necessária.

**INSCRIÇÃO**
• Ao entrar no desafio, cada jogador deve informar **qual carro será utilizado**.
• O carro informado ficará visível para o oponente antes da partida.

**REGRAS DA CORRIDA**
• A partida será **sempre gravada pelo ADM**.
• Será dado **1 ponto ao adversário** caso o jogador:
  • Queime a largada.
  • Passe fora da linha.
  • Capote durante a corrida.

**NÃO É PERMITIDO**
• Hack ou qualquer programa que dê vantagem.
• Utilizar bugs ou exploits de propósito.

Caso seja constatado uso de hack ou bug para obter vantagem, o jogador poderá ser **desclassificado**.

> Antes de iniciar, os dois jogadores devem conferir o carro do adversário e concordar com todas as regras.
"""


def make_drag_topic(creator_id, opponent_id, created=None,
                    creator_agreed=0, opponent_agreed=0,
                    creator_car="", opponent_car="", room_created=0, details=""):
    if created is None:
        created = now_local().isoformat()
    return (
        "GTC_TICKET|"
        f"owner={creator_id}|"
        "type=drag|"
        "claimed=0|"
        f"created={created}|"
        "pix_status=pending|"
        f"opponent={opponent_id}|"
        f"creator_agreed={creator_agreed}|"
        f"opponent_agreed={opponent_agreed}|"
        f"creator_car={creator_car}|"
        f"opponent_car={opponent_car}|"
        f"room_created={room_created}|"
        f"details={details.replace(chr(124), "/")}"
    )


async def update_drag_topic(channel, data):
    # Mantém o nome da função para compatibilidade, mas não edita o topic.
    save_drag_data(channel, data)


class DragOpponentView(discord.ui.View):
    def __init__(self, creator_id):
        super().__init__(timeout=180)
        self.creator_id = creator_id
        self.selected_opponent = None

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="👤 Selecione seu oponente...",
        min_values=1,
        max_values=1,
        custom_id="gtc:drag:opponent"
    )
    async def opponent(self, interaction, select):
        if interaction.user.id != self.creator_id:
            await interaction.response.send_message(
                "❌ Somente quem abriu o desafio pode escolher o oponente.",
                ephemeral=True
            )
            return

        member = select.values[0]
        if member.bot:
            await interaction.response.send_message(
                "❌ Você não pode desafiar um bot.", ephemeral=True
            )
            return
        if member.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Você não pode selecionar a si mesmo.", ephemeral=True
            )
            return
        if user_has_open_ticket(interaction.guild, member.id):
            await interaction.response.send_message(
                "❌ Esse jogador já possui um ticket aberto.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        await create_drag_ticket(interaction, member)
        self.stop()


class DragCarModal(discord.ui.Modal, title="🚗 Informar carro"):
    carro = discord.ui.TextInput(
        label="Qual carro você vai utilizar?",
        placeholder="Ex.: BMW M3 G80",
        required=True,
        min_length=2,
        max_length=80
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction):
        data = get_drag_data(self.channel)
        if not data or data.get("type") != "drag":
            await interaction.response.send_message("❌ Ticket de Drag inválido.", ephemeral=True)
            return

        value = str(self.carro.value).strip().replace("|", "/")
        if interaction.user.id == data["owner"]:
            data["creator_car"] = value
        elif interaction.user.id == int(data.get("opponent", 0)):
            data["opponent_car"] = value
        else:
            await interaction.response.send_message("❌ Você não participa deste desafio.", ephemeral=True)
            return

        await update_drag_topic(self.channel, data)
        await refresh_drag_message(self.channel)
        await interaction.response.send_message("✅ Carro registrado.", ephemeral=True)


class DragDetailsModal(discord.ui.Modal, title="📝 Detalhes do desafio"):
    detalhes = discord.ui.TextInput(
        label="Detalhes do desafio",
        placeholder="Escreva os detalhes que deseja registrar...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction):
        data = get_drag_data(self.channel)
        if not data or data.get("type") != "drag":
            await interaction.response.send_message("❌ Ticket de Drag inválido.", ephemeral=True)
            return

        if interaction.user.id not in (data["owner"], int(data.get("opponent", 0))):
            await interaction.response.send_message("❌ Você não participa deste desafio.", ephemeral=True)
            return

        value = str(self.detalhes.value).strip().replace("|", "/")
        data["details"] = value
        await update_drag_topic(self.channel, data)
        await refresh_drag_message(self.channel)
        await interaction.response.send_message("✅ Detalhes do desafio registrados.", ephemeral=True)


class DragAgreementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚗 Informar meu carro", style=discord.ButtonStyle.secondary, custom_id="gtc:drag:car")
    async def car(self, interaction, button):
        data = get_drag_data(interaction.channel)
        if not data or data.get("type") != "drag":
            await interaction.response.send_message("❌ Este canal não é um desafio de Drag.", ephemeral=True)
            return
        if interaction.user.id not in (data["owner"], int(data.get("opponent", 0))):
            await interaction.response.send_message("❌ Você não participa deste desafio.", ephemeral=True)
            return
        await interaction.response.send_modal(DragCarModal(interaction.channel))

    @discord.ui.button(label="✅ Concordo com as regras", style=discord.ButtonStyle.success, custom_id="gtc:drag:agree")
    async def agree(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        data = get_drag_data(interaction.channel)
        if not data or data.get("type") != "drag":
            await interaction.followup.send("❌ Este canal não é um desafio de Drag.", ephemeral=True)
            return

        if interaction.user.id == data["owner"]:
            data["creator_agreed"] = 1
        elif interaction.user.id == int(data.get("opponent", 0)):
            data["opponent_agreed"] = 1
        else:
            await interaction.followup.send("❌ Você não participa deste desafio.", ephemeral=True)
            return

        await update_drag_topic(interaction.channel, data)
        await refresh_drag_message(interaction.channel)
        await interaction.followup.send("✅ Sua concordância foi registrada.", ephemeral=True)

        data = get_drag_data(interaction.channel)
        if (int(data.get("creator_agreed", 0)) and int(data.get("opponent_agreed", 0))):
            manager_role = get_role(interaction.guild, config["manager_role_id"])
            if manager_role:
                await interaction.channel.send(
                    f"👔 **Acordo finalizado!** {manager_role.mention}\n\n"
                    "Os dois jogadores concordaram com as regras. A Gerência pode criar a sala do Drag."
                )
                await send_log(
                    interaction.guild,
                    "🏁 Acordo de Drag finalizado",
                    f"**Jogadores:** <@{data['owner']}> x <@{data['opponent']}>\n**Canal:** `{interaction.channel.name}`",
                    discord.Color.orange()
                )

    @discord.ui.button(label="📝 Detalhes do desafio", style=discord.ButtonStyle.secondary, custom_id="gtc:drag:details")
    async def details(self, interaction, button):
        data = get_drag_data(interaction.channel)
        if not data or data.get("type") != "drag":
            await interaction.response.send_message("❌ Este canal não é um desafio de Drag.", ephemeral=True)
            return
        if interaction.user.id not in (data["owner"], int(data.get("opponent", 0))):
            await interaction.response.send_message("❌ Você não participa deste desafio.", ephemeral=True)
            return
        modal = DragDetailsModal(interaction.channel)
        modal.detalhes.default = data.get("details", "")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔒 Fechar Ticket", style=discord.ButtonStyle.danger, custom_id="gtc:drag:close")
    async def close_ticket(self, interaction, button):
        data = get_drag_data(interaction.channel)
        if not data or data.get("type") != "drag":
            await interaction.response.send_message(
                "❌ Este canal não é um desafio de Drag.",
                ephemeral=True
            )
            return

        if not is_manager_or_above(interaction.user):
            await interaction.response.send_message(
                "❌ Apenas Gerente ou cargos acima podem fechar este desafio.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            CloseTicketModal(interaction.channel)
        )

    @discord.ui.button(label="🎮 Sala criada", style=discord.ButtonStyle.primary, custom_id="gtc:drag:room")
    async def room(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        data = get_drag_data(interaction.channel)
        if not data or data.get("type") != "drag":
            await interaction.followup.send("❌ Este canal não é um desafio de Drag.", ephemeral=True)
            return
        if not is_manager_or_above(interaction.user):
            await interaction.followup.send("❌ Apenas Gerente ou cargos acima podem confirmar a sala.", ephemeral=True)
            return
        if not (int(data.get("creator_agreed", 0)) and int(data.get("opponent_agreed", 0))):
            await interaction.followup.send("❌ Os dois jogadores ainda precisam concordar com as regras.", ephemeral=True)
            return
        data["room_created"] = 1
        await update_drag_topic(interaction.channel, data)
        await interaction.channel.send(
            f"🎮 **Sala criada pela Gerência!**\n\n"
            f"{interaction.user.mention} confirmou a criação da sala.\n"
            "Os jogadores já podem iniciar o MD3. 🏁"
        )
        await interaction.followup.send("✅ Sala marcada como criada.", ephemeral=True)


async def refresh_drag_message(channel):
    data = get_drag_data(channel)
    if not data:
        return
    creator = channel.guild.get_member(data["owner"])
    opponent = channel.guild.get_member(int(data.get("opponent", 0)))
    creator_name = creator.mention if creator else f"<@{data['owner']}>"
    opponent_name = opponent.mention if opponent else f"<@{data.get('opponent', 0)}>"
    creator_car = data.get("creator_car") or "Não informado"
    opponent_car = data.get("opponent_car") or "Não informado"
    creator_ok = "✅ Concordou" if int(data.get("creator_agreed", 0)) else "⏳ Aguardando"
    opponent_ok = "✅ Concordou" if int(data.get("opponent_agreed", 0)) else "⏳ Aguardando"
    room = "✅ Criada" if int(data.get("room_created", 0)) else "⏳ Aguardando Gerência"
    details = data.get("details") or "Não informado"

    embed = discord.Embed(
        title="🏁 Desafio de Drag — MD3",
        description=(
            f"**Jogadores:** {creator_name} × {opponent_name}\n\n"
            f"**{creator_name}**\n🚗 Carro: **{creator_car}**\n📋 Regras: {creator_ok}\n\n"
            f"**{opponent_name}**\n🚗 Carro: **{opponent_car}**\n📋 Regras: {opponent_ok}\n\n"
            f"🎮 **Sala:** {room}"
        ),
        color=discord.Color.orange(),
        timestamp=now_local()
    )
    embed.add_field(name="📝 Detalhes do desafio", value=details[:1024], inline=False)
    embed.add_field(name="📜 Regras", value=DRAG_RULES, inline=False)
    embed.set_footer(text="GTC Performance • Desafio de Drag")

    # Edita somente a mensagem principal do desafio, identificada pelo primeiro embed do canal.
    async for message in channel.history(limit=20, oldest_first=True):
        if message.author.id == channel.guild.me.id and message.embeds and message.embeds[0].title == "🏁 Desafio de Drag — MD3":
            await message.edit(embed=embed, view=DragAgreementView())
            return


async def create_drag_ticket(interaction, opponent):
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ Isso só funciona dentro do servidor.", ephemeral=True)
        return

    if not atendimento_aberto():
        await interaction.followup.send("🔴 O atendimento está encerrado no momento.", ephemeral=True)
        return

    if user_has_open_ticket(guild, interaction.user.id) or user_has_open_ticket(guild, opponent.id):
        await interaction.followup.send("❌ Um dos jogadores já possui um ticket aberto.", ephemeral=True)
        return

    category = guild.get_channel(1550570219825799189)
    if not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send("❌ Não encontrei a categoria do Desafio de Drag.", ephemeral=True)
        return

    manager_role = get_role(guild, config["manager_role_id"])
    developer_role = get_role(guild, config.get("developer_role_id", 0))
    me = guild.me
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
        opponent: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
    }
    if manager_role:
        overwrites[manager_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
    if developer_role:
        overwrites[developer_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
    if me:
        overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True, attach_files=True, embed_links=True)

    created = now_local().isoformat()
    base = re.sub(r"[^a-z0-9-]", "-", interaction.user.name.lower())[:12]
    opp = re.sub(r"[^a-z0-9-]", "-", opponent.name.lower())[:12]
    channel = await guild.create_text_channel(
        name=f"🏁-drag-{base}-{opp}"[:95],
        category=category,
        overwrites=overwrites,
        topic=make_drag_topic(interaction.user.id, opponent.id, created),
        reason=f"Desafio de Drag aberto por {interaction.user} contra {opponent}"
    )

    save_drag_data(channel, {
        "owner": interaction.user.id,
        "opponent": opponent.id,
        "type": "drag",
        "claimed": 0,
        "created": created,
        "pix_status": "pending",
        "creator_agreed": 0,
        "opponent_agreed": 0,
        "creator_car": "",
        "opponent_car": "",
        "room_created": 0,
        "details": ""
    })

    embed = discord.Embed(
        title="🏁 Desafio de Drag — MD3",
        description=(
            f"**Jogadores:** {interaction.user.mention} × {opponent.mention}\n\n"
            "Os dois jogadores devem informar o carro que será utilizado e ler todas as regras.\n"
            "Depois, cada um deve clicar em **✅ Concordo com as regras**.\n\n"
            "Quando os dois concordarem, a **Gerência será mencionada para criar a sala**."
        ),
        color=discord.Color.orange(),
        timestamp=now_local()
    )
    embed.add_field(name="🚗 Carros", value=f"{interaction.user.mention}: **Não informado**\n{opponent.mention}: **Não informado**", inline=False)
    embed.add_field(name="📋 Concordância", value=f"{interaction.user.mention}: ⏳ Aguardando\n{opponent.mention}: ⏳ Aguardando", inline=False)
    embed.add_field(name="📝 Detalhes do desafio", value="Não informado", inline=False)
    embed.add_field(name="📜 Regras do Drag", value=DRAG_RULES, inline=False)
    embed.set_footer(text="GTC Performance • Desafio de Drag")
    await channel.send(content=f"{interaction.user.mention} {opponent.mention}", embed=embed, view=DragAgreementView())
    await interaction.followup.send(f"✅ Desafio criado: {channel.mention}", ephemeral=True)
    schedule_inactivity(channel)

# ============================================================
# SELECT DO PAINEL
# ============================================================

class TicketTypeSelect(
    discord.ui.Select
):

    def __init__(self):

        options = [

            discord.SelectOption(
                label="Suporte",
                description="Problemas, dúvidas e suporte geral.",
                emoji="🛠️",
                value="suporte"
            ),

            discord.SelectOption(
                label="Acerto",
                description="Acertos e configurações de FuelTech.",
                emoji="💰",
                value="acerto"
            ),

            discord.SelectOption(
                label="Pix",
                description="Pagamentos e acertos via Pix.",
                emoji="💸",
                value="pix"
            ),

            discord.SelectOption(
                label="Teste Preparador",
                description="Solicitação de teste com preparador.",
                emoji="🧪",
                value="teste_preparador"
            ),

            discord.SelectOption(
                label="Desafio de Drag",
                description="Abra um desafio de Drag MD3 contra outro membro.",
                emoji="🏁",
                value="drag"
            )
        ]

        super().__init__(
            placeholder="🎫 Escolha o tipo de atendimento...",
            options=options,
            custom_id="gtc:panel:type"
        )

    async def callback(
        self,
        interaction
    ):

        guild = interaction.guild

        if not guild:

            await interaction.response.send_message(
                "❌ Isso só funciona dentro do servidor.",
                ephemeral=True
            )

            return

        if not atendimento_aberto():

            await interaction.response.send_message(
                "🔴 O atendimento está encerrado no momento.",
                ephemeral=True
            )

            return

        if (
            self.values[0] != "pix"
            and count_open_tickets(guild) >= int(
                config.get(
                    "max_open_tickets",
                    10
                )
            )
        ):

            await interaction.response.send_message(
                "❌ O limite de tickets foi atingido.",
                ephemeral=True
            )

            return

        if user_has_open_ticket(
            guild,
            interaction.user.id
        ):

            await interaction.response.send_message(
                "❌ Você já possui um ticket aberto.",
                ephemeral=True
            )

            return

        ticket_type = self.values[0]

        # ----------------------------------------------------
        # DESAFIO DE DRAG
        # ----------------------------------------------------

        if ticket_type == "drag":

            await interaction.response.send_message(
                "🏁 **Escolha o seu oponente:**",
                view=DragOpponentView(interaction.user.id),
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # SUPORTE
        # ----------------------------------------------------

        if ticket_type == "suporte":

            await interaction.response.send_modal(
                SuporteModal(
                    interaction.user.id
                )
            )

            return

        # ----------------------------------------------------
        # TESTE PREPARADOR
        # ----------------------------------------------------

        if ticket_type == "teste_preparador":

            await interaction.response.send_modal(
                TestePreparadorModal(
                    interaction.user.id
                )
            )

            return

        # ----------------------------------------------------
        # PIX
        # ----------------------------------------------------

        if ticket_type == "pix":

            await interaction.response.send_modal(
                CarModal("pix")
            )

            return

        # ----------------------------------------------------
        # ACERTO
        # ----------------------------------------------------

        if ticket_type == "acerto":

            await interaction.response.send_modal(
                CarModal("acerto")
            )

            return


# ============================================================
# MODAL DO LIMITE
# ============================================================

class TicketLimitModal(
    discord.ui.Modal,
    title="⚙️ Limite de Tickets"
):

    limite = discord.ui.TextInput(
        label="Máximo de tickets abertos",
        placeholder="Exemplo: 10",
        required=True,
        min_length=1,
        max_length=5
    )

    async def on_submit(
        self,
        interaction
    ):

        if not is_manager_or_above(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ Você não tem permissão.",
                ephemeral=True
            )

            return

        try:

            value = int(
                str(
                    self.limite.value
                ).strip()
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ Digite apenas um número inteiro.",
                ephemeral=True
            )

            return

        if value < 1:

            await interaction.response.send_message(
                "❌ O limite mínimo é 1.",
                ephemeral=True
            )

            return

        if value > 10000:

            await interaction.response.send_message(
                "❌ O limite máximo é 10000.",
                ephemeral=True
            )

            return

        config[
            "max_open_tickets"
        ] = value

        save_config()

        await update_panel()

        await interaction.response.send_message(
            f"✅ Limite alterado para **{value} tickets simultâneos**.",
            ephemeral=True
        )

        await send_log(
            interaction.guild,
            "⚙️ Limite alterado",
            (
                f"**Novo limite:** {value}\n"
                f"**Alterado por:** "
                f"{interaction.user.mention}"
            ),
            discord.Color.orange()
        )


# ============================================================
# PAINEL
# ============================================================

class TicketPanelView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        # O botão muda conforme o estado atual do atendimento.
        # Fechado -> abrir excepcional / Aberto excepcional -> encerrar excepcional.
        self.exceptional.label = (
            "Encerrar atendimento excepcional"
            if config.get("exceptional_open", False)
            else "Abrir atendimento excepcional"
        )
        self.exceptional.emoji = (
            "🔒"
            if config.get("exceptional_open", False)
            else "🔓"
        )

        self.add_item(
            TicketTypeSelect()
        )

    @discord.ui.button(
        label="Configurar limite",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        custom_id="gtc:panel:limit"
    )
    async def configure_limit(
        self,
        interaction,
        button
    ):

        if not is_manager_or_above(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ Apenas Gerente ou cargos acima podem alterar o limite.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            TicketLimitModal()
        )

    @discord.ui.button(
        label="Atendimento excepcional",
        emoji="🔓",
        style=discord.ButtonStyle.danger,
        custom_id="gtc:panel:exceptional"
    )
    async def exceptional(
        self,
        interaction,
        button
    ):

        if not is_manager_or_above(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ Apenas Gerente ou cargos acima podem alterar o atendimento.",
                ephemeral=True
            )

            return

        config[
            "exceptional_open"
        ] = not config.get(
            "exceptional_open",
            False
        )

        save_config()

        await update_panel()

        if config[
            "exceptional_open"
        ]:

            await interaction.response.send_message(
                "🔓 Atendimento excepcional **aberto**.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "🔒 Atendimento excepcional **encerrado**.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Anunciar Tickets",
        emoji="📢",
        style=discord.ButtonStyle.primary,
        custom_id="gtc:panel:announce"
    )
    async def announce_tickets(
        self,
        interaction,
        button
    ):

        if not is_manager_or_above(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ Apenas Gerente ou cargos acima podem anunciar os tickets.",
                ephemeral=True
            )

            return

        guild = interaction.guild

        if not guild:

            await interaction.response.send_message(
                "❌ Isso só funciona dentro do servidor.",
                ephemeral=True
            )

            return

        general_channel = guild.get_channel(
            int(
                config.get(
                    "general_channel_id",
                    1543697522906636438
                )
            )
        )

        if not general_channel:

            await interaction.response.send_message(
                "❌ Não encontrei o canal **geral**. Renomeie o canal para `geral` ou `chat-geral`.",
                ephemeral=True
            )

            return

        maximum = int(
            config.get(
                "max_open_tickets",
                10
            )
        )

        await general_channel.send(
            content=(
                f"{maximum} TICKETS ON\n\n"
                "@here"
            ),
            allowed_mentions=discord.AllowedMentions(
                everyone=True
            )
        )

        await interaction.response.send_message(
            f"✅ Anúncio enviado em {general_channel.mention}: **{maximum} TICKETS ON @here**",
            ephemeral=True
        )


def create_panel_embed(
    guild
):

    current = count_open_tickets(
        guild
    )

    maximum = int(
        config.get(
            "max_open_tickets",
            10
        )
    )

    embed = discord.Embed(
        title="🎫 GTC PERFORMANCE — ATENDIMENTO",
        description=(
            "Bem-vindo ao sistema de atendimento da "
            "**GTC Performance**.\n\n"
            "Selecione abaixo o tipo de atendimento que você precisa.\n\n"
            f"**Status:** {status_text()}\n"
            f"**Tickets abertos:** {current}/{maximum}\n\n"
            "⚠️ Você só pode possuir "
            "**1 ticket aberto por vez**."
            "\n\n⛽ **IMPORTANTE:** A GTC Performance **não realiza acertos de carros na gasolina**."
        ),
        color=(
            discord.Color.green()
            if atendimento_aberto()
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="🛠️ Suporte",
        value="Dúvidas e suporte geral.",
        inline=True
    )

    embed.add_field(
        name="💰 Acerto",
        value="Acertos de FuelTech.",
        inline=True
    )

    embed.add_field(
        name="💸 Pix",
        value="Pagamentos.",
        inline=True
    )

    embed.add_field(
        name="🧪 Teste Preparador",
        value="Testes com preparador.",
        inline=True
    )

    embed.set_footer(
        text="GTC Performance • Sistema de Tickets"
    )

    embed.description += (
        "\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🕐 **HORÁRIOS DE ATENDIMENTO**\n"
        "🟢 **10:00 às 12:30**\n"
        "🟢 **13:30 às 19:00**\n"
        "🟢 **21:00 às 00:00**\n"
        "📅 **Todos os dias • Horário de Brasília**"
    )

    return embed


async def update_panel():

    guild = bot.get_guild(
        int(
            config["guild_id"]
        )
    )

    if not guild:
        return

    channel = guild.get_channel(
        int(
            config.get(
                "panel_channel_id",
                0
            )
        )
    )

    if not isinstance(
        channel,
        discord.TextChannel
    ):
        return

    message_id = int(
        config.get(
            "panel_message_id",
            0
        )
    )

    if message_id:

        try:

            message = await channel.fetch_message(
                message_id
            )

            await message.edit(
                embed=create_panel_embed(
                    guild
                ),
                view=TicketPanelView()
            )

            return

        except discord.NotFound:
            pass

        except Exception as error:

            print(
                f"[PANEL] {error}"
            )

    try:

        message = await channel.send(
            embed=create_panel_embed(
                guild
            ),
            view=TicketPanelView()
        )

        config[
            "panel_message_id"
        ] = message.id

        save_config()

    except Exception as error:

        print(
            f"[PANEL] {error}"
        )


# ============================================================
# INATIVIDADE
# ============================================================

activity_tasks = {}
activity_versions = {}
pix_receipt_tasks = {}

# Estado dinâmico dos desafios de Drag fica fora do topic do canal.
# Alterar o topic a cada clique dispara o rate limit de edição de canais do Discord.
DRAG_STATE_FILE = BASE_DIR / "drag_states.json"
drag_states = {}


def load_drag_states():
    global drag_states
    try:
        if DRAG_STATE_FILE.exists():
            raw = json.loads(DRAG_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                drag_states = raw
    except Exception as error:
        print(f"[DRAG STATE] Erro ao carregar estados: {error}")
        drag_states = {}


def save_drag_states():
    try:
        DRAG_STATE_FILE.write_text(
            json.dumps(drag_states, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as error:
        print(f"[DRAG STATE] Erro ao salvar estados: {error}")


def get_drag_data(channel):
    key = str(channel.id)
    if key in drag_states:
        data = dict(drag_states[key])
        data["owner"] = int(data["owner"])
        data["opponent"] = int(data.get("opponent", 0) or 0)
        data["claimed"] = int(data.get("claimed", 0) or 0)
        return data

    data = parse_topic(channel.topic)
    if not data or data.get("type") != "drag":
        return None

    drag_states[key] = {
        "owner": data["owner"],
        "opponent": int(data.get("opponent", 0) or 0),
        "type": "drag",
        "claimed": int(data.get("claimed", 0) or 0),
        "created": data.get("created"),
        "pix_status": data.get("pix_status", "pending"),
        "creator_agreed": int(data.get("creator_agreed", 0) or 0),
        "opponent_agreed": int(data.get("opponent_agreed", 0) or 0),
        "creator_car": data.get("creator_car", ""),
        "opponent_car": data.get("opponent_car", ""),
        "room_created": int(data.get("room_created", 0) or 0),
        "details": data.get("details", "")
    }
    save_drag_states()
    return dict(drag_states[key])


def save_drag_data(channel, data):
    drag_states[str(channel.id)] = {
        "owner": int(data["owner"]),
        "opponent": int(data.get("opponent", 0) or 0),
        "type": "drag",
        "claimed": int(data.get("claimed", 0) or 0),
        "created": data.get("created"),
        "pix_status": data.get("pix_status", "pending"),
        "creator_agreed": int(data.get("creator_agreed", 0) or 0),
        "opponent_agreed": int(data.get("opponent_agreed", 0) or 0),
        "creator_car": data.get("creator_car", ""),
        "opponent_car": data.get("opponent_car", ""),
        "room_created": int(data.get("room_created", 0) or 0),
        "details": data.get("details", "")
    }
    save_drag_states()


def delete_drag_data(channel_id):
    if drag_states.pop(str(channel_id), None) is not None:
        save_drag_states()


load_drag_states()


def cancel_pix_receipt_task(channel_id):
    task = pix_receipt_tasks.pop(channel_id, None)
    if task:
        # O próprio timer chama close_ticket() quando os 10 minutos acabam.
        # Não podemos cancelar a task que está executando o fechamento,
        # senão o asyncio pode interromper o fechamento antes de apagar o canal.
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None

        if task is not current_task:
            task.cancel()


def schedule_pix_receipt_timeout(channel):
    cancel_pix_receipt_task(channel.id)
    data = parse_topic(channel.topic)
    if not data or data.get("type") != "pix" or data.get("pix_status", "pending") != "pending":
        return
    pix_receipt_tasks[channel.id] = asyncio.create_task(pix_receipt_timeout_worker(channel))


async def pix_receipt_timeout_worker(channel):
    try:
        data = parse_topic(channel.topic)
        if not data or data.get("type") != "pix" or data.get("pix_status", "pending") != "pending":
            return
        remaining = 600
        try:
            created = datetime.fromisoformat(data["created"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=TZ)
            remaining = max(0, 600 - (now_local() - created).total_seconds())
        except Exception:
            pass
        await asyncio.sleep(remaining)
        data = parse_topic(channel.topic)
        if not data or data.get("type") != "pix" or data.get("pix_status", "pending") != "pending":
            return
        await channel.send("⏰ **Tempo esgotado.**\n\nNão recebemos um comprovante Pix válido para análise dentro de 10 minutos. O ticket será encerrado automaticamente.")
        await asyncio.sleep(2)
        print(f"[PIX TIMEOUT] Fechando ticket automaticamente: {channel.id}")
        await close_ticket(channel, None, "Ticket Pix fechado automaticamente por não envio de comprovante em 10 minutos.", automatic=True)
    except asyncio.CancelledError:
        return
    except Exception as error:
        print(f"[PIX TIMEOUT] {error}")
    finally:
        pix_receipt_tasks.pop(channel.id, None)


def cancel_activity_task(
    channel_id
):

    task = activity_tasks.pop(
        channel_id,
        None
    )

    if task:
        task.cancel()


def schedule_inactivity(
    channel
):

    cancel_activity_task(
        channel.id
    )

    version = activity_versions.get(
        channel.id,
        0
    ) + 1

    activity_versions[
        channel.id
    ] = version

    activity_tasks[
        channel.id
    ] = asyncio.create_task(
        inactivity_worker(
            channel,
            version
        )
    )


async def inactivity_worker(
    channel,
    version
):

    try:

        await asyncio.sleep(
            40 * 60
        )

        # Timer antigo nunca pode fechar um ticket que recebeu mensagem.
        if activity_versions.get(
            channel.id
        ) != version:
            return

        if channel.id not in activity_tasks:
            return

        data = parse_topic(
            channel.topic
        )

        if not data:
            return

        try:

            last_message = None

            async for message in channel.history(
                limit=1
            ):

                last_message = message
                break

            if last_message:

                elapsed = (
                    datetime.now(timezone.utc)
                    - last_message.created_at
                ).total_seconds()

                if elapsed < (
                    40 * 60
                ):

                    schedule_inactivity(
                        channel
                    )

                    return

        except discord.NotFound:
            # O canal pode ter sido fechado/apagado por outra rotina.
            return

        except Exception as error:

            print(
                f"[INACTIVITY] {error}"
            )

        # Última proteção contra corrida entre o timer e uma mensagem nova.
        if activity_versions.get(
            channel.id
        ) != version:
            return

        await close_ticket(
            channel,
            None,
            "Ticket fechado automaticamente por 40 minutos de inatividade.",
            automatic=True
        )

    except asyncio.CancelledError:

        return

    except Exception as error:

        print(
            f"[INACTIVITY] {error}"
        )

    finally:

        activity_tasks.pop(
            channel.id,
            None
        )


# ============================================================
# BOT
# ============================================================

async def mover_pix_para_categoria_comprovantes(channel, data=None):
    """Atualiza categoria, topic e permissões Pix em uma única edição."""
    guild = channel.guild
    if not guild:
        return False

    target_id = int(config.get("pix_final_category_id", 1548089221820977173))
    target = guild.get_channel(target_id)
    if not isinstance(target, discord.CategoryChannel):
        print(f"[PIX] Categoria final {target_id} não encontrada ou não é categoria.")
        return False

    try:
        if data is None:
            data = parse_topic(channel.topic)

        overwrites = dict(channel.overwrites)
        manager_role = get_role(guild, config.get("manager_role_id", 0))

        if manager_role:
            overwrites[manager_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

        await channel.edit(
            category=target,
            topic=make_topic(
                data["owner"],
                data["type"],
                data.get("claimed", 0),
                data.get("created"),
                data.get("payment"),
                data.get("pix_status", "pending")
            ),
            overwrites=overwrites,
            reason="Comprovante Pix enviado; transferindo ticket para categoria de conferência."
        )
        return True
    except Exception as error:
        print(f"[PIX] Erro ao mover ticket para categoria final: {error}")
        return False


def permission_overwrite_matches(channel, role, expected):
    current = channel.overwrites_for(role)
    return all(
        getattr(current, key) == value
        for key, value in expected.items()
    )


class GTCBot(
    commands.Bot
):

    def __init__(self):

        intents = discord.Intents.default()

        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(
        self
    ):

        self.add_view(
            TicketPanelView()
        )

        self.add_view(
            TicketControlView()
        )

        self.add_view(
            DragAgreementView()
        )

        guild = discord.Object(
            id=int(
                config["guild_id"]
            )
        )

        self.tree.copy_global_to(
            guild=guild
        )

        synced = await self.tree.sync(
            guild=guild
        )

        print(
            f"[SLASH] "
            f"{len(synced)} comandos sincronizados."
        )

    async def on_ready(
        self
    ):

        print(
            "=" * 60
        )

        print(
            "GTC PERFORMANCE BOT ONLINE"
        )

        print(
            "=" * 60
        )

        print(
            f"Bot: {self.user}"
        )

        print(
            f"ID: {self.user.id}"
        )

        if pytesseract is not None and TESSERACT_EXE:
            try:
                print(f"OCR: Tesseract {pytesseract.get_tesseract_version()}")
                print(f"OCR executável: {TESSERACT_EXE}")
                print(f"OCR idiomas: {', '.join(pytesseract.get_languages(config=''))}")
            except Exception as error:
                print(f"OCR: erro ao inicializar Tesseract: {error}")
        else:
            print("OCR: Tesseract não configurado.")

        print(
            f"Servidor: "
            f"{config['guild_id']}"
        )

        print(
            f"Tickets máximos: "
            f"{config.get('max_open_tickets', 10)}"
        )

        print(
            "=" * 60
        )

        if not panel_updater.is_running():

            panel_updater.start()

        await update_panel()

        guild = self.get_guild(
            int(config["guild_id"])
        )

        if not guild:
            print("[PIX] Guild configurada não foi encontrada no cache.")
            return

        for channel in get_ticket_channels(
            guild
        ):

            schedule_inactivity(
                channel
            )

            data = parse_topic(channel.topic)
            if data and data.get("type") == "pix":
                # Normaliza tickets Pix já existentes após reiniciar o bot:
                # Gerência fica sem acesso enquanto o comprovante estiver pendente
                # e recebe acesso quando o ticket já estiver em análise.
                manager_role = get_role(
                    channel.guild,
                    config.get("manager_role_id", 0)
                )
                pix_status = data.get("pix_status", "pending")
                pending_category = guild.get_channel(
                    int(config.get("ticket_categories", {}).get("pix", 1550344537774493746))
                )
                final_category = guild.get_channel(
                    int(config.get("pix_final_category_id", 1548089221820977173))
                )

                # Normaliza a categoria de tickets Pix após reiniciar o bot.
                # Pendente fica na categoria privada; comprovante já enviado
                # fica na categoria final de conferência.
                try:
                    target_category = (
                        final_category
                        if pix_status in ("received", "review")
                        else pending_category
                    )
                    if isinstance(target_category, discord.CategoryChannel) and channel.category_id != target_category.id:
                        await channel.edit(
                            category=target_category,
                            reason="Normalização automática da categoria do ticket Pix."
                        )
                except Exception as error:
                    print(f"[PIX] Erro ao normalizar categoria no startup: {error}")

                if manager_role:
                    manager_expected = (
                        {
                            "view_channel": True,
                            "send_messages": True,
                            "read_message_history": True,
                            "attach_files": True,
                            "embed_links": True
                        }
                        if pix_status in ("received", "review")
                        else {
                            "view_channel": False,
                            "send_messages": False,
                            "read_message_history": False,
                            "attach_files": False,
                            "embed_links": False
                        }
                    )
                    if not permission_overwrite_matches(channel, manager_role, manager_expected):
                        await channel.set_permissions(manager_role, **manager_expected)

                if pix_status not in ("received", "review"):
                    for restricted_role in (
                        get_role(channel.guild, config.get("support_role_id", 0)),
                        get_role(channel.guild, config.get("preparador_role_id", 0))
                    ):
                        if restricted_role:
                            restricted_expected = {
                                "view_channel": False,
                                "send_messages": False,
                                "read_message_history": False,
                                "attach_files": False,
                                "embed_links": False
                            }
                            if not permission_overwrite_matches(channel, restricted_role, restricted_expected):
                                await channel.set_permissions(restricted_role, **restricted_expected)

                schedule_pix_receipt_timeout(channel)

    async def on_message(
    self,
    message
    ):

        if message.author.bot:
            return

        channel = message.channel

        if isinstance(
            channel,
            discord.TextChannel
        ):

            data = parse_topic(
                channel.topic
            )

            if data:

                schedule_inactivity(
                    channel
                )

                # ----------------------------------------------------
                # PIX: VERIFICAÇÃO AUTOMÁTICA DE COMPROVANTE
                # ----------------------------------------------------

                if data.get("type") == "pix" and message.attachments:
                    result = await verificar_comprovante_pix(message)
                    status = result.get("status", "nao_comprovante")

                    if status == "comprovante":
                        cancel_pix_receipt_task(channel.id)
                        data["pix_status"] = "received"
                        await mover_pix_para_categoria_comprovantes(channel, data)
                        await channel.send("📄 **Possível comprovante Pix detectado.**\n👔 A Gerência recebeu acesso ao ticket para conferir.\n⚠️ O bot só identifica sinais; **o pagamento precisa ser confirmado manualmente.**")

                    elif status == "suspeito":
                        cancel_pix_receipt_task(channel.id)
                        data["pix_status"] = "review"
                        await mover_pix_para_categoria_comprovantes(channel, data)
                        await channel.send("🚨 **Atenção: comprovante precisa de conferência.**\n\nA imagem contém sinais de uma transferência, mas o destinatário não pôde ser confirmado como o esperado.\n\n👔 A Gerência foi chamada para analisar manualmente.\n⚠️ Isso **não significa automaticamente que houve golpe**. O bot não confirma fraude sozinho.")

                    elif status == "ilegivel":
                        await channel.send("⚠️ **Não foi possível compreender o comprovante.**\n\nA imagem parece estar ilegível, cortada ou com informação insuficiente para a leitura automática. Envie o **comprovante Pix completo e legível**.\n\n⏱️ O prazo de 10 minutos continua valendo.")

                    elif status == "nao_comprovante":
                        await channel.send("❌ **Essa imagem não parece ser um comprovante Pix.**\n\nNão foram encontrados sinais suficientes de uma transação Pix. Se você já realizou o pagamento, envie o **comprovante completo e legível**.\n\n⚠️ Imagens aleatórias, prints sem relação com o pagamento ou imagens cortadas não serão consideradas comprovante.\n⏱️ O prazo de 10 minutos continua valendo.")

                    elif status == "indisponivel":
                        await channel.send("⚠️ **Não foi possível verificar a imagem automaticamente.**\n\nEnvie o comprovante Pix completo e legível mesmo assim. A equipe poderá fazer a conferência manual.")

        await self.process_commands(
            message
        )

bot = GTCBot()


# ============================================================
# ATUALIZAÇÃO DO PAINEL
# ============================================================

@tasks.loop(
    seconds=60
)
async def panel_updater():

    try:

        await update_panel()

    except Exception as error:

        print(
            f"[PANEL LOOP] {error}"
        )


# ============================================================
# /SETUP-TICKET
# ============================================================

@bot.tree.command(
    name="setup-ticket",
    description="Cria ou atualiza o painel de tickets."
)
async def setup_ticket(
    interaction
):

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Apenas Gerente ou cargos acima podem usar este comando.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    await update_panel()

    await interaction.followup.send(
        "✅ Painel de tickets atualizado.",
        ephemeral=True
    )


# ============================================================
# /STATUS-TICKET
# ============================================================

@bot.tree.command(
    name="status-ticket",
    description="Mostra ou altera o status do atendimento."
)
@app_commands.describe(
    acao="Escolha a ação."
)
@app_commands.choices(
    acao=[
        app_commands.Choice(
            name="Mostrar status",
            value="mostrar"
        ),
        app_commands.Choice(
            name="Abrir excepcional",
            value="abrir"
        ),
        app_commands.Choice(
            name="Encerrar excepcional",
            value="fechar"
        )
    ]
)
async def status_ticket(
    interaction,
    acao: app_commands.Choice[str]
):

    if acao.value == "mostrar":

        await interaction.response.send_message(
            (
                f"**Status:** {status_text()}\n"
                f"**Tickets:** "
                f"{count_open_tickets(interaction.guild)}/"
                f"{config.get('max_open_tickets', 10)}"
            ),
            ephemeral=True
        )

        return

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Apenas Gerente ou cargos acima podem alterar o status.",
            ephemeral=True
        )

        return

    if acao.value == "abrir":

        config[
            "exceptional_open"
        ] = True

        save_config()

        await update_panel()

        await interaction.response.send_message(
            "🔓 Atendimento excepcional aberto.",
            ephemeral=True
        )

    elif acao.value == "fechar":

        config[
            "exceptional_open"
        ] = False

        save_config()

        await update_panel()

        await interaction.response.send_message(
            "🔒 Atendimento excepcional encerrado.",
            ephemeral=True
        )


# ============================================================
# /HORARIO
# ============================================================

@bot.tree.command(
    name="horario",
    description="Mostra os horários de atendimento."
)
async def horario(
    interaction
):

    names = [
        ("monday", "Segunda-feira"),
        ("tuesday", "Terça-feira"),
        ("wednesday", "Quarta-feira"),
        ("thursday", "Quinta-feira"),
        ("friday", "Sexta-feira"),
        ("saturday", "Sábado"),
        ("sunday", "Domingo")
    ]

    lines = []

    for key, name in names:

        periods = config[
            "business_hours"
        ].get(
            key,
            []
        )

        formatted = " • ".join(
            f"{start}–{end}"
            for start, end in periods
        )

        lines.append(
            f"**{name}:** {formatted}"
        )

    embed = discord.Embed(
        title="🕐 Horário de Atendimento",
        description="\n".join(lines),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="Status atual",
        value=status_text(),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# /CONFIG
# ============================================================

config_group = app_commands.Group(
    name="config",
    description="Configurações do sistema de tickets."
)


# ------------------------------------------------------------
# /CONFIG VER
# ------------------------------------------------------------

@config_group.command(
    name="ver",
    description="Mostra a configuração atual."
)
async def config_ver(
    interaction
):

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Apenas Gerente ou cargos acima podem usar este comando.",
            ephemeral=True
        )

        return

    guild = interaction.guild

    support = get_role(
        guild,
        config["support_role_id"]
    )

    preparador = get_role(
        guild,
        config["preparador_role_id"]
    )

    manager = get_role(
        guild,
        config["manager_role_id"]
    )

    embed = discord.Embed(
        title="⚙️ Configuração — GTC Performance",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="👮 Cargos",
        value=(
            f"**Suporte:** "
            f"{support.mention if support else 'Não configurado'}\n"
            f"**Preparador:** "
            f"{preparador.mention if preparador else 'Não configurado'}\n"
            f"**Gerente:** "
            f"{manager.mention if manager else 'Não configurado'}"
        ),
        inline=False
    )

    embed.add_field(
        name="🎫 Tickets",
        value=(
            f"**Limite:** "
            f"{config.get('max_open_tickets', 10)}\n"
            f"**Abertos:** "
            f"{count_open_tickets(guild)}\n"
            f"**Status:** "
            f"{status_text()}"
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ------------------------------------------------------------
# /CONFIG CARGO
# ------------------------------------------------------------

@config_group.command(
    name="cargo",
    description="Configura um cargo do sistema."
)
@app_commands.describe(
    tipo="Cargo que deseja configurar.",
    cargo="Novo cargo."
)
@app_commands.choices(
    tipo=[
        app_commands.Choice(
            name="Suporte",
            value="suporte"
        ),
        app_commands.Choice(
            name="Preparador",
            value="preparador"
        ),
        app_commands.Choice(
            name="Gerente",
            value="gerente"
        )
    ]
)
async def config_cargo(
    interaction,
    tipo: app_commands.Choice[str],
    cargo: discord.Role
):

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Você não tem permissão.",
            ephemeral=True
        )

        return

    if tipo.value == "suporte":

        config[
            "support_role_id"
        ] = cargo.id

    elif tipo.value == "preparador":

        config[
            "preparador_role_id"
        ] = cargo.id

    elif tipo.value == "gerente":

        config[
            "manager_role_id"
        ] = cargo.id

    save_config()

    await interaction.response.send_message(
        (
            f"✅ Cargo de **{tipo.name}** "
            f"definido como {cargo.mention}."
        ),
        ephemeral=True
    )


# ------------------------------------------------------------
# /CONFIG LOGS
# ------------------------------------------------------------

@config_group.command(
    name="logs",
    description="Define o canal de logs."
)
async def config_logs(
    interaction,
    canal: discord.TextChannel
):

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Você não tem permissão.",
            ephemeral=True
        )

        return

    config[
        "logs_channel_id"
    ] = canal.id

    save_config()

    await interaction.response.send_message(
        f"✅ Canal de logs definido como {canal.mention}.",
        ephemeral=True
    )


# ------------------------------------------------------------
# /CONFIG CATEGORIA
# ------------------------------------------------------------

@config_group.command(
    name="categoria",
    description="Define a categoria de um tipo de ticket."
)
@app_commands.describe(
    tipo="Tipo de ticket.",
    categoria="Categoria do Discord."
)
@app_commands.choices(
    tipo=[
        app_commands.Choice(
            name="Suporte",
            value="suporte"
        ),
        app_commands.Choice(
            name="Acerto",
            value="acerto"
        ),
        app_commands.Choice(
            name="Pix",
            value="pix"
        ),
        app_commands.Choice(
            name="Teste Preparador",
            value="teste_preparador"
        )
    ]
)
async def config_categoria(
    interaction,
    tipo: app_commands.Choice[str],
    categoria: discord.CategoryChannel
):

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Você não tem permissão.",
            ephemeral=True
        )

        return

    config[
        "ticket_categories"
    ][tipo.value] = categoria.id

    save_config()

    await interaction.response.send_message(
        (
            f"✅ Categoria de **{tipo.name}** "
            f"definida como **{categoria.name}**."
        ),
        ephemeral=True
    )


# ------------------------------------------------------------
# /CONFIG HORARIO
# ------------------------------------------------------------

@config_group.command(
    name="horario",
    description="Altera o horário de atendimento."
)
@app_commands.describe(
    dia="Dia da semana.",
    inicio="Horário inicial, exemplo: 10:00.",
    fim="Horário final, exemplo: 12:30."
)
@app_commands.choices(
    dia=[
        app_commands.Choice(
            name="Segunda-feira",
            value="monday"
        ),
        app_commands.Choice(
            name="Terça-feira",
            value="tuesday"
        ),
        app_commands.Choice(
            name="Quarta-feira",
            value="wednesday"
        ),
        app_commands.Choice(
            name="Quinta-feira",
            value="thursday"
        ),
        app_commands.Choice(
            name="Sexta-feira",
            value="friday"
        ),
        app_commands.Choice(
            name="Sábado",
            value="saturday"
        ),
        app_commands.Choice(
            name="Domingo",
            value="sunday"
        )
    ]
)
async def config_horario(
    interaction,
    dia: app_commands.Choice[str],
    inicio: str,
    fim: str
):

    if not is_manager_or_above(
        interaction.user
    ):

        await interaction.response.send_message(
            "❌ Você não tem permissão.",
            ephemeral=True
        )

        return

    pattern = r"^(?:[01]\d|2[0-3]):[0-5]\d$"

    if not re.match(
        pattern,
        inicio
    ):

        await interaction.response.send_message(
            "❌ O horário inicial deve estar no formato `HH:MM`.",
            ephemeral=True
        )

        return

    if (
        fim != "00:00"
        and not re.match(
            pattern,
            fim
        )
    ):

        await interaction.response.send_message(
            "❌ O horário final deve estar no formato `HH:MM`.",
            ephemeral=True
        )

        return

    config[
        "business_hours"
    ][dia.value] = [
        [inicio, fim]
    ]

    save_config()

    await update_panel()

    await interaction.response.send_message(
        (
            f"✅ Horário de **{dia.name}** alterado para "
            f"**{inicio}–{fim}**."
        ),
        ephemeral=True
    )


bot.tree.add_command(
    config_group,
    guild=discord.Object(
        id=int(
            config["guild_id"]
        )
    )
)


# ============================================================
# ERROS
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print(
        f"[SLASH ERROR] {error}"
    )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ Ocorreu um erro ao executar esse comando.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ Ocorreu um erro ao executar esse comando.",
                ephemeral=True
            )

    except Exception:
        pass


# ============================================================
# INÍCIO
# ============================================================

if __name__ == "__main__":

    bot.run(
        TOKEN
    )
