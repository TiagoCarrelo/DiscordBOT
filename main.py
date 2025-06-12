import discord
from discord.ext import commands
from datetime import datetime, timedelta
import json
import nest_asyncio
import asyncio
import os
import random
from flask import Flask
from threading import Thread
from discord import app_commands
from database import buscar_historico
from datetime import datetime


nest_asyncio.apply()

INTERVALO_PRESENCA_SEGUNDOS = 60

MENSAGENS_PRESENCA = [
    "🔔 {user}, estamos esperando sua confirmação de presença.",
    "🕒 Ei {user}, confirme sua presença antes que o ponto seja encerrado!",
    "⚠️ {user}, não esqueça de marcar **✅ Presente** agora!",
    "👀 {user}, você está aí? Confirme presença ou perderá o ponto!",
    "✅ Lembrete para {user}: confirme sua presença clicando no botão.",
    "🛎️ {user}, confirme presença ou seu ponto será encerrado em breve.",
]

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv('GUILD_ID'))
CANAL_HISTORICO_ID = 1236901325758005299
ID_ROLE_FINALIZAR = 1084846765984981123  

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="/", intents=intents)
data_ponto = {}

def salvar_dados():
    with open("ponto.json", "w") as f:
        json.dump(data_ponto, f, indent=2)

def formatar_hora_iso(iso):
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%d/%m/%Y às %H:%M")

def calcular_tempo_total(historico, como_texto=True):
    inicio = fim = None
    pausas, voltas = [], []

    for item in historico:
        acao, hora = item["acao"], datetime.fromisoformat(item["hora"])
        if acao == "✅ Início":
            inicio = hora
        elif acao == "🔴 Finalizar":
            fim = hora
        elif acao == "⏸️ Pausa":
            pausas.append(hora)
        elif acao == "▶️ Voltar":
            voltas.append(hora)

    if not inicio or not fim:
        return "Não finalizado." if como_texto else None

    total = fim - inicio
    for pausa, volta in zip(pausas, voltas):
        total -= (volta - pausa)

    total_minutos = total.total_seconds() // 60
    if como_texto:
        horas, minutos = divmod(int(total_minutos), 60)
        return f"{horas}h {minutos}min"
    else:
        return int(total_minutos)

def gerar_embed(user: discord.User, user_data):
    embed = discord.Embed(title="🕐 Relatório de Ponto", color=0x5865F2)
    embed.add_field(name="Usuário", value=user.mention, inline=False)

    historico = user_data.get("historico", [])
    texto_hist = ""
    for item in historico:
        texto_hist += f"**{item['acao']}**: {formatar_hora_iso(item['hora'])}\n"

    if any(i["acao"] == "🔴 Finalizar" for i in historico):
        texto_hist += f"\n**Tempo total:** {calcular_tempo_total(historico)}"

    embed.add_field(name="📋 Histórico", value=texto_hist or "Nenhuma ação registrada.", inline=False)
    embed.set_footer(text="Sistema de Ponto - Hostcarioca")
    return embed

class PontoView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.estado = "pausavel"
        self.embed_msg = None
        self.aviso_msg = None
        self.presenca_confirmada = False

        if self.user_id not in data_ponto:
            data_ponto[self.user_id] = {"historico": []}

        self.atualizar_botoes()

    def registrar_acao(self, acao):
        data_ponto[self.user_id]["historico"].append({
            "acao": acao,
            "hora": datetime.utcnow().isoformat()
        })
        salvar_dados()

    def atualizar_botoes(self):
        self.clear_items()
        if self.estado == "pausavel":
            self.add_item(self.pausar)
        elif self.estado == "voltavel":
            self.add_item(self.voltar)
        if self.estado != "finalizado":
            self.add_item(self.presente)
            self.add_item(self.finalizar)

    async def loop_verificacao_presenca(self):
        while self.estado != "finalizado":
            self.presenca_confirmada = False
            await asyncio.sleep(INTERVALO_PRESENCA_SEGUNDOS)

            if self.estado == "finalizado":
                break

            if not self.presenca_confirmada:
                self.registrar_acao("🔴 Finalizar")
                self.estado = "finalizado"
                self.atualizar_botoes()
                await self.atualizar_embed_msg()

                canal = self.embed_msg.channel
                await canal.send(
                    f"⚠️ <@{self.user_id}> não confirmou presença e o ponto foi encerrado automaticamente.\n<@&{ID_ROLE_FINALIZAR}> foi notificada."
                )

                canal_hist = canal.guild.get_channel(CANAL_HISTORICO_ID)
                if canal_hist:
                    membro = canal.guild.get_member(int(self.user_id))
                    await canal_hist.send(embed=gerar_embed(membro, data_ponto[self.user_id]))
                break

            try:
                minutos = INTERVALO_PRESENCA_SEGUNDOS // 60
                msg = random.choice(MENSAGENS_PRESENCA).format(user=f"<@{self.user_id}>")
                msg += f"\nVocê tem {minutos} minutos antes do ponto ser encerrado automaticamente."
                self.aviso_msg = await self.embed_msg.channel.send(msg)
            except Exception as e:
                print("Erro ao enviar nova mensagem de presença:", e)

    async def atualizar_embed_msg(self):
        if not self.embed_msg:
            return

        try:
            canal = self.embed_msg.channel
            mensagem_atual = await canal.fetch_message(self.embed_msg.id)
            guild = canal.guild

            membro = guild.get_member(int(self.user_id))
            if membro is None:
                membro = await guild.fetch_member(int(self.user_id))

            embed = gerar_embed(membro, data_ponto[self.user_id])
            await mensagem_atual.edit(embed=embed, view=self)
        except Exception as e:
            print(f"Erro ao atualizar embed: {e}")

    @discord.ui.button(label="⏸️ Pausa", style=discord.ButtonStyle.secondary, custom_id="pausa")
    async def pausar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Apenas o dono pode interagir.", ephemeral=True)
        self.registrar_acao("⏸️ Pausa")
        self.estado = "voltavel"
        self.atualizar_botoes()
        await self.atualizar_embed_msg()
        await interaction.response.defer()

    @discord.ui.button(label="▶️ Voltar", style=discord.ButtonStyle.primary, custom_id="voltar")
    async def voltar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Apenas o dono pode interagir.", ephemeral=True)
        self.registrar_acao("▶️ Voltar")
        self.estado = "pausavel"
        self.atualizar_botoes()
        await self.atualizar_embed_msg()
        await interaction.response.defer()

    @discord.ui.button(label="✅ Presente", style=discord.ButtonStyle.success, custom_id="presente")
    async def presente(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Apenas o dono pode interagir.", ephemeral=True)
        self.presenca_confirmada = True
        await interaction.response.send_message("✅ Presença confirmada!", ephemeral=True)
        if self.aviso_msg:
            try:
                await self.aviso_msg.delete()
            except:
                pass
            self.aviso_msg = None
        await self.atualizar_embed_msg()

    @discord.ui.button(label="🔴 Finalizar", style=discord.ButtonStyle.danger, custom_id="finalizar")
    async def finalizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        tem_permissao = (
            str(user.id) == self.user_id or
            discord.utils.get(user.roles, id=ID_ROLE_FINALIZAR) is not None
        )
        if not tem_permissao:
            return await interaction.response.send_message("❌ Apenas o dono do ponto ou a equipe autorizada pode finalizar.", ephemeral=True)
        self.registrar_acao("🔴 Finalizar")
        self.estado = "finalizado"
        self.atualizar_botoes()
        await self.atualizar_embed_msg()
        await interaction.response.defer()
        await interaction.message.edit(view=None)

        canal_hist = interaction.guild.get_channel(CANAL_HISTORICO_ID)
        if canal_hist:
            usuario = interaction.guild.get_member(int(self.user_id))
            embed = gerar_embed(usuario or interaction.user, data_ponto[self.user_id])
            await canal_hist.send(embed=embed)

@bot.event
async def on_message_delete(message):
    for view in bot.persistent_views:
        if isinstance(view, PontoView) and view.embed_msg and message.id == view.embed_msg.id:
            if view.estado != "finalizado":
                view.registrar_acao("🔴 Finalizar")
                view.estado = "finalizado"
                view.atualizar_botoes()
                salvar_dados()
                try:
                    canal = message.channel
                    guild = message.guild

                    membro = guild.get_member(int(view.user_id))
                    if membro is None:
                        membro = await guild.fetch_member(int(view.user_id))

                    await canal.send(
                        f"⚠️ {membro.mention}, sua mensagem de ponto foi apagada. "
                        f"O ponto foi encerrado automaticamente.\n<@&{ID_ROLE_FINALIZAR}> foi notificada."
                    )

                    canal_hist = guild.get_channel(CANAL_HISTORICO_ID)
                    if canal_hist:
                        embed = gerar_embed(membro, data_ponto[view.user_id])
                        await canal_hist.send(embed=embed)

                except Exception as e:
                    print(f"Erro ao finalizar ponto por deleção da mensagem: {e}")

@bot.tree.command(name="ponto", description="Inicia o sistema de ponto.")
async def ponto(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    historico = data_ponto.get(user_id, {}).get("historico", [])

    if any(i["acao"] == "✅ Início" for i in historico) and not any(i["acao"] == "🔴 Finalizar" for i in historico):
        return await interaction.response.send_message("❌ Você já iniciou o ponto.", ephemeral=True)

    data_ponto[user_id] = {
        "historico": [{"acao": "✅ Início", "hora": datetime.utcnow().isoformat()}]
    }
    salvar_dados()

    view = PontoView(user_id)
    embed = gerar_embed(interaction.user, data_ponto[user_id])
    await interaction.response.send_message(embed=embed, view=view)
    view.embed_msg = await interaction.original_response()

    minutos = INTERVALO_PRESENCA_SEGUNDOS // 60
    view.aviso_msg = await interaction.channel.send(
        f"🔔 {interaction.user.mention}, confirme sempre sua presença clicando em **✅ Presente**.\n"
        f"Você tem {minutos} minutos antes do ponto ser encerrado automaticamente."
    )

    asyncio.create_task(view.loop_verificacao_presenca())

@bot.tree.command(name="historico", description="Exibe todos os registros de ponto finalizados.")
@app_commands.checks.cooldown(1, 10)
async def historico_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    # Substitua pela função real de carregamento do banco ou arquivo se necessário
    user_data = data_ponto.get(user_id)

    if not user_data or not user_data.get("historico"):
        return await interaction.response.send_message("❌ Nenhum histórico encontrado.", ephemeral=True)

    embed = discord.Embed(title="📜 Histórico de Ponto Finalizado", color=discord.Color.blurple())
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)

    blocos = []
    bloco_atual = []

    for acao in user_data["historico"]:
        bloco_atual.append(acao)
        if acao["acao"] == "🔴 Finalizar":
            blocos.append(bloco_atual)
            bloco_atual = []

    if not blocos:
        return await interaction.response.send_message("⚠️ Nenhum ponto finalizado encontrado.", ephemeral=True)

    for idx, bloco in enumerate(blocos[-5:], start=1):  # Mostra os últimos 5 registros
        data_fim = next((a["hora"] for a in bloco if a["acao"] == "🔴 Finalizar"), None)
        if data_fim:
            try:
                data_fim_formatada = datetime.fromisoformat(data_fim).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                data_fim_formatada = data_fim
        else:
            data_fim_formatada = "Data inválida"

        tempo_total = calcular_tempo_total(bloco)
        embed.add_field(
            name=f"🔹 Registro #{idx} - {data_fim_formatada}",
            value=f"Tempo total: **{tempo_total}**",
            inline=False
        )

    embed.set_footer(text="Últimos 5 pontos finalizados.")
    await interaction.response.send_message(embed=embed, ephemeral=True)




app = Flask("")

@app.route('/')
def home():
    return "✅ Bot online!"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()
bot.run(TOKEN)
