from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import (
    ChannelParticipantAdmin, ChannelParticipantCreator, 
    MessageEntityUrl, MessageEntityTextUrl, ChatBannedRights,
    UpdateGroupCall, UpdateGroupCallParticipants, InputChannel
)
from telethon.errors import UserAdminInvalidError, ChatAdminRequiredError
from datetime import datetime, timedelta
import asyncio
import re
import json
import os
import time
import logging
from threading import Thread

# Loglama yapılandırması
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# API kimlik bilgileri
API_ID = 28857104
API_HASH = "c288d8be9f64e231b721c0b2f338b105"
BOT_TOKEN = "8065737316:AAFk6RBwAgHYKaNmhi8svJuqwGmDfRYQd3Q"
LOG_CHANNEL_ID = -1002288700632

# Farklı log kategorileri için thread ID'leri
THREAD_IDS = {
    "ban": 2173,
    "mute": 2172,
    "forbidden_words": 2171,
    "join_leave": 2144,
    "kicks": 2173,  # Bu thread'i oluşturmanız gerekecek
    "warns": 0,  # Bu thread'i oluşturmanız gerekecek
    "voice_chats": 2260,  # Bu thread'i oluşturmanız gerekecek
    "repeated_msgs": 0,  # Bu thread'i oluşturmanız gerekecek
    "appeals": 0,  # Bu thread'i oluşturmanız gerekecek
}

# Yapılandırma dosya yolu
CONFIG_FILE = 'bot_config.json'

# Varsayılan yapılandırma
DEFAULT_CONFIG = {
    "groups": {},
    "forbidden_words": {},
    "repeated_messages": {},
    "welcome_messages": {},
    "warn_settings": {},
    "admin_permissions": {},
    "active_calls": {}  # Sesli aramaları takip etmek için
}

# İstemciyi başlat
client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Yapılandırmayı yükle
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

# Yapılandırmayı kaydet
def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# Global yapılandırma
config = load_config()

# Grubun yapılandırmada olduğundan emin ol
def ensure_group_in_config(chat_id):
    chat_id_str = str(chat_id)
    if chat_id_str not in config["groups"]:
        config["groups"][chat_id_str] = {
            "forbidden_words": [],
            "welcome_message": {
                "enabled": False,
                "text": "Gruba hoş geldiniz!",
                "buttons": []
            },
            "repeated_messages": {
                "enabled": False,
                "interval": 3600,
                "messages": [],
                "with_image": False,
                "buttons": []
            },
            "warn_settings": {
                "max_warns": 3,
                "action": "ban",  # veya "mute"
                "mute_duration": 24  # saat
            },
            "admin_permissions": {}
        }
        save_config(config)
    return chat_id_str

# Yönetici izinlerini kontrol et
# Yönetici izinlerini kontrol et - geliştirilmiş versiyon
async def check_admin_permission(event, permission_type):
    try:
        # Özel mesajlar için otomatik izin ver
        if event.is_private:
            return True
            
        chat = await event.get_chat()
        sender = await event.get_sender()
        chat_id_str = str(chat.id)
        
        # Kullanıcının kurucu olup olmadığını kontrol et
        try:
            if hasattr(chat, 'id') and hasattr(chat, 'username') or hasattr(chat, 'title'):  # Kanal ya da grup olduğundan emin ol
                participant = await client(GetParticipantRequest(
                    channel=chat,
                    participant=sender.id
                ))
                if isinstance(participant.participant, ChannelParticipantCreator):
                    return True
        except Exception as e:
            # Sadece debug amaçlı logluyoruz, hatayı bastırmıyoruz
            if "InputPeerUser" not in str(e):  # Bilinen hatayı loglama
                logger.debug(f"Kurucu durumu kontrol edilirken hata oluştu: {e}")
        
        # Özel izinleri kontrol et
        if chat_id_str in config["groups"]:
            admin_permissions = config["groups"][chat_id_str].get("admin_permissions", {})
            if str(sender.id) in admin_permissions:
                if permission_type in admin_permissions[str(sender.id)]:
                    return True
        
        # Normal yönetici izinlerini kontrol et
        try:
            if hasattr(chat, 'id') and (hasattr(chat, 'username') or hasattr(chat, 'title')):  # Kanal ya da grup olduğundan emin ol
                participant = await client(GetParticipantRequest(
                    channel=chat,
                    participant=sender.id
                ))
                if isinstance(participant.participant, ChannelParticipantAdmin):
                    admin_rights = participant.participant.admin_rights
                    if permission_type == "ban" and admin_rights.ban_users:
                        return True
                    elif permission_type == "mute" and admin_rights.ban_users:
                        return True
                    elif permission_type == "kick" and admin_rights.ban_users:
                        return True
                    elif permission_type == "warn" and admin_rights.ban_users:
                        return True
                    elif permission_type == "edit_group" and admin_rights.change_info:
                        return True
                    elif permission_type == "add_admin" and admin_rights.add_admins:
                        return True
        except Exception as e:
            # Sadece debug amaçlı logluyoruz, hatayı bastırmıyoruz
            if "InputPeerUser" not in str(e):  # Bilinen hatayı loglama
                logger.debug(f"Yönetici izinlerini kontrol ederken hata oluştu: {e}")
        
        # Bot geliştiricisi veya belirli bir kullanıcı ID'si için arka kapı
        if sender.id == 123456789:  # Buraya kendi ID'nizi ekleyebilirsiniz
            return True
            
        return False
    except Exception as e:
        logger.debug(f"İzin kontrolü sırasında genel hata: {e}")
        # Hata olunca varsayılan olarak izin verme
        return False

# Uygun thread'e log gönder
async def log_to_thread(log_type, text, buttons=None, *args):
    thread_id = THREAD_IDS.get(log_type, 0)
    if thread_id:
        try:
            if buttons:
                await client.send_message(
                    LOG_CHANNEL_ID, 
                    text, 
                    buttons=buttons,
                    reply_to=thread_id
                )
            else:
                await client.send_message(
                    LOG_CHANNEL_ID, 
                    text,
                    reply_to=thread_id
                )
        except Exception as e:
            logger.error(f"Thread'e log gönderirken hata oluştu: {e}")

# Raw Updates - Sesli sohbet tespiti için
@client.on(events.Raw)
async def voice_chat_handler(event):
    try:
        if isinstance(event, UpdateGroupCall):
            # Sesli sohbet başlatıldı veya sonlandırıldı
            chat_id = event.chat_id
            call = event.call
            
            # Aktif aramalar sözlüğünü kontrol et
            if "active_calls" not in config:
                config["active_calls"] = {}
                
            call_id_str = str(call.id)
            is_new_call = False
            
            if call_id_str not in config["active_calls"]:
                # Yeni başlatılan sesli sohbet
                is_new_call = True
                config["active_calls"][call_id_str] = {
                    "chat_id": chat_id,
                    "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "participants": []
                }
                save_config(config)
                
                try:
                    chat = await client.get_entity(chat_id)
                    
                    # Log metni
                    log_text = f"🎙️ **SESLİ SOHBET BAŞLATILDI**\n\n" \
                            f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    await log_to_thread("voice_chats", log_text, chat.id, None)
                except Exception as e:
                    logger.error(f"Sesli sohbet başlatma loglanırken hata oluştu: {e}")
            
            # Arama sonlandırıldı mı kontrol et
            if not is_new_call and not call.schedule_date and hasattr(call, 'duration'):
                # Arama sonlandırıldı
                try:
                    chat = await client.get_entity(chat_id)
                    call_data = config["active_calls"].get(call_id_str, {})
                    start_time_str = call_data.get("start_time", "Bilinmiyor")
                    
                    # Başlangıç ve bitiş zamanları arasındaki farkı hesapla
                    duration = "Bilinmiyor"
                    try:
                        start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
                        end_time = datetime.now()
                        duration_seconds = int((end_time - start_time).total_seconds())
                        
                        hours, remainder = divmod(duration_seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        
                        if hours > 0:
                            duration = f"{hours} saat, {minutes} dakika, {seconds} saniye"
                        elif minutes > 0:
                            duration = f"{minutes} dakika, {seconds} saniye"
                        else:
                            duration = f"{seconds} saniye"
                    except:
                        pass
                    
                    # Log metni
                    log_text = f"🎙️ **SESLİ SOHBET SONLANDIRILDI**\n\n" \
                            f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                            f"**Süre:** {duration}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    await log_to_thread("voice_chats", log_text, chat.id, None)
                    
                    # Aktif aramalardan kaldır
                    if call_id_str in config["active_calls"]:
                        del config["active_calls"][call_id_str]
                        save_config(config)
                        
                except Exception as e:
                    logger.error(f"Sesli sohbet bitirme loglanırken hata oluştu: {e}")
                    
        elif isinstance(event, UpdateGroupCallParticipants):
            # Sesli sohbet katılımcıları güncellendi
            participants = event.participants
            call = event.call
            
            if "active_calls" not in config:
                config["active_calls"] = {}
                
            call_id_str = str(call.id)
            
            if call_id_str in config["active_calls"]:
                # Her katılımcı için
                for participant in participants:
                    user_id = participant.user_id
                    is_joining = not participant.left
                    
                    # Kullanıcı listesini güncelle
                    if is_joining and user_id not in config["active_calls"][call_id_str]["participants"]:
                        config["active_calls"][call_id_str]["participants"].append(user_id)
                        save_config(config)
                        
                        # Katılmayı logla
                        try:
                            chat_id = config["active_calls"][call_id_str]["chat_id"]
                            chat = await client.get_entity(chat_id)
                            user = await client.get_entity(user_id)
                            
                            log_text = f"🎙️ **SESLİ SOHBETE KATILDI**\n\n" \
                                    f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            
                            await log_to_thread("voice_chats", log_text, chat.id, None)
                        except Exception as e:
                            logger.error(f"Sesli sohbete katılma loglanırken hata oluştu: {e}")
                            
                    elif participant.left and user_id in config["active_calls"][call_id_str]["participants"]:
                        config["active_calls"][call_id_str]["participants"].remove(user_id)
                        save_config(config)
                        
                        # Ayrılmayı logla
                        try:
                            chat_id = config["active_calls"][call_id_str]["chat_id"]
                            chat = await client.get_entity(chat_id)
                            user = await client.get_entity(user_id)
                            
                            log_text = f"🎙️ **SESLİ SOHBETTEN AYRILDI**\n\n" \
                                    f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            
                            await log_to_thread("voice_chats", log_text, chat.id, None)
                        except Exception as e:
                            logger.error(f"Sesli sohbetten ayrılma loglanırken hata oluştu: {e}")
    except Exception as e:
        logger.error(f"Sesli sohbet event işleyicisinde hata: {e}")

# MODERASYON KOMUTLARI
# Anti-flood functionality - Paste this code at the end of your existing code before client.run_until_disconnected()

# Dictionary to track user messages: {chat_id: {user_id: [message_timestamps]}}
user_messages = {}

# Default flood settings for each chat


# Add flood config to existing config

# Ban komutu
@client.on(events.NewMessage(pattern=r'/ban(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def ban_command(event):
    if not await check_admin_permission(event, "ban"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    reason = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Banlamak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen ban sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    
    try:
        banned_user = await client.get_entity(user_id)
        await client(EditBannedRequest(
            chat.id,
            user_id,
            ChatBannedRights(
                until_date=None,
                view_messages=True,
                send_messages=True,
                send_media=True,
                send_stickers=True,
                send_gifs=True,
                send_games=True,
                send_inline=True,
                embed_links=True
            )
        ))
        
        # İtiraz butonu oluştur
        appeal_button = Button.inline("Bana İtiraz Et", data=f"appeal_ban_{user_id}")
        
        # Ban'i logla
        log_text = f"🚫 **KULLANICI BANLANDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {banned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("ban", log_text, [[appeal_button]], chat.id)
        
        await event.respond(f"Kullanıcı {banned_user.first_name} şu sebepten banlandı: {reason}")
    except UserAdminInvalidError:
        await event.respond("Bir yöneticiyi banlayamam.")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Unban komutu (YENİ)
@client.on(events.NewMessage(pattern=r'/unban(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def unban_command(event):
    if not await check_admin_permission(event, "ban"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    reason = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Ban kaldırmak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen ban kaldırma sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    
    try:
        unbanned_user = await client.get_entity(user_id)
        await client(EditBannedRequest(
            chat.id,
            user_id,
            ChatBannedRights(
                until_date=None,
                view_messages=False,
                send_messages=False,
                send_media=False,
                send_stickers=False,
                send_gifs=False,
                send_games=False,
                send_inline=False,
                embed_links=False
            )
        ))
        
        # Ban kaldırmayı logla
        log_text = f"✅ **KULLANICI BANI KALDIRILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {unbanned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("ban", log_text, None, chat.id)
        
        await event.respond(f"Kullanıcı {unbanned_user.first_name} ban kaldırıldı. Sebep: {reason}")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Mute komutu
@client.on(events.NewMessage(pattern=r'/mute(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+(\d+)([dhm]))?(\s+.+)?'))
async def mute_command(event):
    if not await check_admin_permission(event, "mute"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    duration_num = event.pattern_match.group(3)
    duration_unit = event.pattern_match.group(4)
    reason = event.pattern_match.group(5)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Susturmak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen susturma sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    
    # Mute süresini hesapla
    until_date = None
    if duration_num and duration_unit:
        duration = int(duration_num)
        if duration_unit == 'd':
            until_date = datetime.now() + timedelta(days=duration)
            duration_text = f"{duration} gün"
        elif duration_unit == 'h':
            until_date = datetime.now() + timedelta(hours=duration)
            duration_text = f"{duration} saat"
        elif duration_unit == 'm':
            until_date = datetime.now() + timedelta(minutes=duration)
            duration_text = f"{duration} dakika"
    else:
        # Varsayılan: 1 gün sustur
        until_date = datetime.now() + timedelta(days=1)
        duration_text = "1 gün"
    
    try:
        muted_user = await client.get_entity(user_id)
        await client(EditBannedRequest(
            chat.id,
            user_id,
            ChatBannedRights(
                until_date=until_date,
                send_messages=True,
                send_media=True,
                send_stickers=True,
                send_gifs=True,
                send_games=True,
                send_inline=True,
                embed_links=True
            )
        ))
        
        # İtiraz butonu oluştur
        appeal_button = Button.inline("Susturmaya İtiraz Et", data=f"appeal_mute_{user_id}")
        
        # Mute'u logla
        until_text = "süresiz" if not until_date else f"{until_date.strftime('%Y-%m-%d %H:%M:%S')} tarihine kadar"
        log_text = f"🔇 **KULLANICI SUSTURULDU**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {muted_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Süre:** {duration_text}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("mute", log_text, [[appeal_button]], chat.id)
        
        await event.respond(f"Kullanıcı {muted_user.first_name} {duration_text} boyunca şu sebepten susturuldu: {reason}")
    except UserAdminInvalidError:
        await event.respond("Bir yöneticiyi susturamam.")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Unmute komutu (YENİ)
@client.on(events.NewMessage(pattern=r'/unmute(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def unmute_command(event):
    if not await check_admin_permission(event, "mute"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    reason = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Susturmayı kaldırmak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen susturmayı kaldırma sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    
    try:
        unmuted_user = await client.get_entity(user_id)
        await client(EditBannedRequest(
            chat.id,
            user_id,
            ChatBannedRights(
                until_date=None,
                send_messages=False,
                send_media=False,
                send_stickers=False,
                send_gifs=False,
                send_games=False,
                send_inline=False,
                embed_links=False
            )
        ))
        
        # Susturma kaldırmayı logla
        log_text = f"🔊 **KULLANICI SUSTURMASI KALDIRILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {unmuted_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("mute", log_text, None, chat.id)
        
        await event.respond(f"Kullanıcı {unmuted_user.first_name} susturması kaldırıldı. Sebep: {reason}")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Kick komutu
@client.on(events.NewMessage(pattern=r'/kick(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def kick_command(event):
    if not await check_admin_permission(event, "kick"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    reason = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Atmak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen atma sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    
    try:
        kicked_user = await client.get_entity(user_id)
        
        # Kullanıcıyı at ve sonra yasağı kaldır
        await client(EditBannedRequest(
            chat.id,
            user_id,
            ChatBannedRights(
                until_date=None,
                view_messages=True
            )
        ))
        
        await client(EditBannedRequest(
            chat.id,
            user_id,
            ChatBannedRights(
                until_date=None,
                view_messages=False
            )
        ))
        
        # Kick'i logla
        log_text = f"👢 **KULLANICI ATILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {kicked_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("kicks", log_text, chat.id, None)
        
        await event.respond(f"Kullanıcı {kicked_user.first_name} şu sebepten gruptan atıldı: {reason}")
    except UserAdminInvalidError:
        await event.respond("Bir yöneticiyi atamam.")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Uyarı komutu
@client.on(events.NewMessage(pattern=r'/warn(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def warn_command(event):
    if not await check_admin_permission(event, "warn"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    reason = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Uyarmak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen uyarı sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    # Kullanıcının uyarılarını kontrol et
    if "user_warnings" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["user_warnings"] = {}
    
    user_id_str = str(user_id)
    if user_id_str not in config["groups"][chat_id_str]["user_warnings"]:
        config["groups"][chat_id_str]["user_warnings"][user_id_str] = []
    
    # Yeni uyarı ekle
    warning = {
        "reason": reason,
        "admin_id": event.sender_id,
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    config["groups"][chat_id_str]["user_warnings"][user_id_str].append(warning)
    save_config(config)
    
    # Uyarı sayısını kontrol et
    warn_count = len(config["groups"][chat_id_str]["user_warnings"][user_id_str])
    warn_settings = config["groups"][chat_id_str]["warn_settings"]
    
    try:
        warned_user = await client.get_entity(user_id)
        
        # Uyarıyı logla
        log_text = f"⚠️ **KULLANICI UYARILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {warned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # İtiraz butonu oluştur
        appeal_button = Button.inline("Uyarıya İtiraz Et", data=f"appeal_warn_{user_id}")
        
        await log_to_thread("warns", log_text, [[appeal_button]], chat.id)
        
        response = f"Kullanıcı {warned_user.first_name} şu sebepten uyarıldı: {reason}\n" \
                  f"Uyarı Sayısı: {warn_count}/{warn_settings['max_warns']}"
        
        # Maksimum uyarı sayısına ulaşıldıysa ceza uygula
        if warn_count >= warn_settings['max_warns']:
            if warn_settings['action'] == 'ban':
                await client(EditBannedRequest(
                    chat.id,
                    user_id,
                    ChatBannedRights(
                        until_date=None,
                        view_messages=True,
                        send_messages=True,
                        send_media=True,
                        send_stickers=True,
                        send_gifs=True,
                        send_games=True,
                        send_inline=True,
                        embed_links=True
                    )
                ))
                
                response += f"\n\nKullanıcı maksimum uyarı sayısına ulaştığı için banlandı!"
                
                # Ban'i logla
                log_text = f"🚫 **KULLANICI UYARILAR NEDENİYLE BANLANDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {warned_user.first_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                          f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("ban", log_text, [[appeal_button]], chat.id)
                
            elif warn_settings['action'] == 'mute':
                mute_duration = warn_settings.get('mute_duration', 24)  # Saat cinsinden
                until_date = datetime.now() + timedelta(hours=mute_duration)
                
                await client(EditBannedRequest(
                    chat.id,
                    user_id,
                    ChatBannedRights(
                        until_date=until_date,
                        send_messages=True,
                        send_media=True,
                        send_stickers=True,
                        send_gifs=True,
                        send_games=True,
                        send_inline=True,
                        embed_links=True
                    )
                ))
                
                response += f"\n\nKullanıcı maksimum uyarı sayısına ulaştığı için {mute_duration} saat susturuldu!"
                
                # Mute'u logla
                log_text = f"🔇 **KULLANICI UYARILAR NEDENİYLE SUSTURULDU**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {warned_user.first_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                          f"**Süre:** {mute_duration} saat\n" \
                          f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("mute", log_text, [[appeal_button]], chat.id)
            
            # Uyarı sayısını sıfırla
            config["groups"][chat_id_str]["user_warnings"][user_id_str] = []
            save_config(config)
        
        await event.respond(response)
        
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Unwarn komutu (YENİ)
@client.on(events.NewMessage(pattern=r'/unwarn(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def unwarn_command(event):
    if not await check_admin_permission(event, "warn"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    reason = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Uyarı kaldırmak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    if not reason:
        await event.respond("Lütfen uyarı kaldırma sebebi belirtin.")
        return
    
    reason = reason.strip()
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    user_id_str = str(user_id)
    
    # Kullanıcının uyarıları var mı kontrol et
    if ("user_warnings" not in config["groups"][chat_id_str] or 
        user_id_str not in config["groups"][chat_id_str]["user_warnings"] or
        not config["groups"][chat_id_str]["user_warnings"][user_id_str]):
        await event.respond("Bu kullanıcının hiç uyarısı yok.")
        return
    
    # Son uyarıyı kaldır
    removed_warning = config["groups"][chat_id_str]["user_warnings"][user_id_str].pop()
    save_config(config)
    
    try:
        warned_user = await client.get_entity(user_id)
        
        # Kalan uyarı sayısı
        warn_count = len(config["groups"][chat_id_str]["user_warnings"][user_id_str])
        warn_settings = config["groups"][chat_id_str]["warn_settings"]
        
        # Uyarı kaldırmayı logla
        log_text = f"⚠️ **KULLANICI UYARISI KALDIRILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {warned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Kalan Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("warns", log_text, chat.id, None)
        
        await event.respond(f"Kullanıcı {warned_user.first_name} bir uyarısı kaldırıldı.\n"
                          f"Kalan Uyarı Sayısı: {warn_count}/{warn_settings['max_warns']}\n"
                          f"Sebep: {reason}")
        
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Kullanıcı bilgisi komutu
@client.on(events.NewMessage(pattern=r'/info(?:@\w+)?(\s+(?:@\w+|\d+))?'))
async def info_command(event):
    args = event.pattern_match.group(1)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Bilgi almak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    try:
        user = await client.get_entity(user_id)
        
        # Kullanıcının gruba katılma tarihini al
        join_date = "Bilinmiyor"
        try:
            participant = await client(GetParticipantRequest(chat, user_id))
            join_date = participant.participant.date.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
        
        # Kullanıcının mesaj sayısını al (bu örnek için varsayılan bir değer)
        message_count = "Bilinmiyor"
        
        # Kullanıcının uyarı sayısını al
        warn_count = 0
        if "user_warnings" in config["groups"][chat_id_str]:
            if str(user_id) in config["groups"][chat_id_str]["user_warnings"]:
                warn_count = len(config["groups"][chat_id_str]["user_warnings"][str(user_id)])
        
        # Kullanıcı bilgisini hazırla
        user_info = f"👤 **KULLANICI BİLGİSİ**\n\n" \
                   f"**İsim:** {user.first_name}" + (f" {user.last_name}" if user.last_name else "") + "\n" \
                   f"**Kullanıcı Adı:** @{user.username}\n" if user.username else "" \
                   f"**ID:** `{user_id}`\n" \
                   f"**Gruba Katılma:** {join_date}\n" \
                   f"**Mesaj Sayısı:** {message_count}\n" \
                   f"**Uyarı Sayısı:** {warn_count}"
        
        # Yönetim butonlarını hazırla
        ban_button = Button.inline("🚫 Ban", data=f"action_ban_{user_id}")
        mute_button = Button.inline("🔇 Sustur", data=f"action_mute_{user_id}")
        kick_button = Button.inline("👢 At", data=f"action_kick_{user_id}")
        warn_button = Button.inline("⚠️ Uyar", data=f"action_warn_{user_id}")
        
        buttons = [
            [ban_button, mute_button],
            [kick_button, warn_button]
        ]
        
        await event.respond(user_info, buttons=buttons)
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# BUTON İŞLEYİCİLERİ
# Basit günlük istatistik özelliği
# bot.py dosyasının sonuna ekleyin (main() fonksiyonundan önce)
# Basit günlük istatistik özelliği
# bot.py dosyasının sonuna ekleyin (main() fonksiyonundan önce)
import pytz
from telethon.tl.functions.channels import GetFullChannelRequest

# Thread ID for stats in the log channel
if "stats" not in THREAD_IDS:
    # You need to create this thread in your log channel
    THREAD_IDS["stats"] = 0  # Gerçek thread ID ile değiştirin

# Basit günlük istatistikler
daily_stats = {
    "new_members": {},  # {chat_id: count}
    "left_members": {},  # {chat_id: count}
    "messages": {}      # {chat_id: count}
}

# İstatistikleri sıfırla
def reset_daily_stats():
    for key in daily_stats:
        daily_stats[key] = {}

# İstatistikleri dosyaya kaydet
def save_stats():
    stats_file = 'bot_stats.json'
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(daily_stats, f, indent=4, ensure_ascii=False)

# İstatistikleri dosyadan yükle
def load_stats():
    global daily_stats
    stats_file = 'bot_stats.json'
    if os.path.exists(stats_file):
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                daily_stats = json.load(f)
        except:
            reset_daily_stats()
    else:
        reset_daily_stats()
        save_stats()

# Bir istatistiği artır
def increment_stat(stat_type, chat_id):
    chat_id_str = str(chat_id)
    if chat_id_str not in daily_stats[stat_type]:
        daily_stats[stat_type][chat_id_str] = 0
    daily_stats[stat_type][chat_id_str] += 1
    save_stats()

# Bir grup için istatistik raporu oluştur
async def generate_stats_report(chat_id):
    chat_id_str = str(chat_id)
    
    try:
        # Grup bilgisini al
        chat = await client.get_entity(int(chat_id))
        
        # Katılımcı sayısını al
        try:
            full_chat = await client(GetFullChannelRequest(chat))
            member_count = full_chat.full_chat.participants_count
        except:
            member_count = "Bilinmiyor"
        
        # İstatistikleri topla
        new_members = daily_stats["new_members"].get(chat_id_str, 0)
        left_members = daily_stats["left_members"].get(chat_id_str, 0)
        messages = daily_stats["messages"].get(chat_id_str, 0)
        
        # Net üye değişimi
        net_change = new_members - left_members
        change_emoji = "📈" if net_change > 0 else "📉" if net_change < 0 else "➖"
        
        # Raporu oluştur
        report = f"📊 **GÜNLÜK İSTATİSTİK RAPORU**\n\n"
        report += f"**Grup:** {chat.title} (`{chat.id}`)\n"
        report += f"**Tarih:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
        
        report += f"**Üye Sayısı:** {member_count}\n"
        report += f"**Üye Değişimi:** {change_emoji} {net_change:+d}\n"
        report += f"➖ Yeni Üyeler: {new_members}\n"
        report += f"➖ Ayrılan Üyeler: {left_members}\n\n"
        
        report += f"**Aktivite:**\n"
        report += f"💬 Mesaj Sayısı: {messages}\n"
        
        return report, chat.title
    
    except Exception as e:
        logger.error(f"İstatistik raporu oluşturulurken hata: {e}")
        return f"İstatistik raporu oluşturulurken hata oluştu: {str(e)}", "Bilinmeyen Grup"

# Günlük istatistik raporunu gönder
async def send_daily_report():
    while True:
        try:
            # Türkiye zaman diliminde mevcut saati al
            turkey_tz = pytz.timezone('Europe/Istanbul')
            now = datetime.now(turkey_tz)
            
            # Hedef zamanı ayarla (Türkiye saatiyle akşam 9)
            target_time = now.replace(hour=21, minute=0, second=0, microsecond=0)
            
            # Eğer mevcut zaman hedef zamandan daha ilerideyse, hedefi yarına ayarla
            if now.time() >= target_time.time():
                target_time = target_time + timedelta(days=1)
            
            # Hedef zamana kadar beklenecek saniye sayısını hesapla
            wait_seconds = (target_time - now).total_seconds()
            
            # Hedef zamana kadar bekle
            await asyncio.sleep(wait_seconds)
            
            # Tüm aktif gruplar için log kanalına rapor gönder
            all_reports = ""
            for chat_id_str in config["groups"]:
                try:
                    chat_id = int(chat_id_str)
                    report, chat_title = await generate_stats_report(chat_id)
                    
                    # Her grup için ayrı bir rapor ekle
                    all_reports += f"{report}\n{'─' * 30}\n\n"
                    
                except Exception as e:
                    logger.error(f"İstatistik raporu oluşturulurken hata ({chat_id_str}): {e}")
            
            # Tüm raporları birleştirerek tek bir mesajda gönder
            if all_reports:
                header = f"📊 **TÜM GRUPLARIN GÜNLÜK İSTATİSTİK RAPORU**\n" \
                        f"**Tarih:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                
                # Log kanalındaki thread'e gönder
                await log_to_thread("stats", header + all_reports, None, chat.id)
            
            # Raporları gönderdikten sonra istatistikleri sıfırla
            reset_daily_stats()
            save_stats()
            
            # Çoklu rapor gönderimini önlemek için biraz bekle
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Günlük rapor göndericisinde hata: {e}")
            await asyncio.sleep(60)  # Hata sonrası tekrar denemeden önce bekle

# Anlık istatistikleri gösterme komutu - sadece admin kullanabilir
@client.on(events.NewMessage(pattern=r'/stat(?:@\w+)?'))
async def stat_command(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat_id = event.chat_id
    report, _ = await generate_stats_report(chat_id)
    await event.respond(report)

# İstatistikleri toplamak için event handler'ları

# Yeni üye katılımlarını izle
@client.on(events.ChatAction(func=lambda e: e.user_joined or e.user_added))
async def track_new_members(event):
    increment_stat("new_members", event.chat_id)

# Üyelerin ayrılmasını izle
@client.on(events.ChatAction(func=lambda e: e.user_kicked or e.user_left))
async def track_left_members(event):
    increment_stat("left_members", event.chat_id)

# Mesajları izle
@client.on(events.NewMessage)
async def track_messages(event):
    if not event.is_private and event.message:
        increment_stat("messages", event.chat_id)

# Ana fonksiyonu güncelle

# Yönetim işlem butonları
@client.on(events.CallbackQuery(pattern=r'action_(ban|mute|kick|warn)_(\d+)'))
async def action_button_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        
        permission_type = action
        if not await check_admin_permission(event, permission_type):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # İşlem türüne göre kullanıcıdan bir sebep isteyin
        action_names = {
            "ban": "banlamak",
            "mute": "susturmak",
            "kick": "atmak",
            "warn": "uyarmak"
        }
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            # Sebep sor
            await conv.send_message(f"Kullanıcıyı {action_names[action]} için bir sebep girin:")
            reason_response = await conv.get_response()
            reason = reason_response.text
            
            if action == "mute":
                # Süre sor
                await conv.send_message("Susturma süresi belirtin (örn. '1d', '12h', '30m'):")
                duration_response = await conv.get_response()
                duration_text = duration_response.text
                
                duration_match = re.match(r'(\d+)([dhm])', duration_text)
                if duration_match:
                    duration_num = int(duration_match.group(1))
                    duration_unit = duration_match.group(2)
                else:
                    await conv.send_message("Geçersiz süre formatı. Varsayılan olarak 1 gün uygulanacak.")
                    duration_num = 1
                    duration_unit = 'd'
            
            # Komutları chat'te çalıştır
            if action == "ban":
                await client.send_message(conv.chat_id, f"/ban {user_id} {reason}")
            elif action == "mute":
                await client.send_message(conv.chat_id, f"/mute {user_id} {duration_num}{duration_unit} {reason}")
            elif action == "kick":
                await client.send_message(conv.chat_id, f"/kick {user_id} {reason}")
            elif action == "warn":
                await client.send_message(conv.chat_id, f"/warn {user_id} {reason}")
    except Exception as e:
        logger.error(f"Buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# İtiraz işleme butonları
@client.on(events.CallbackQuery(pattern=r'appeal_(ban|mute|warn)_(\d+)'))
async def appeal_button_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        
        if event.sender_id != user_id:
            await event.answer("Bu butonu sadece ceza alan kullanıcı kullanabilir.", alert=True)
            return
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            
            # İtiraz sebebi sor
            await conv.send_message(f"{action.capitalize()} cezasına itiraz sebebinizi yazın:")
            reason_response = await conv.get_response()
            appeal_reason = reason_response.text
            
            # İtirazı logla
            action_names = {
                "ban": "Ban",
                "mute": "Susturma",
                "warn": "Uyarı"
            }
            
            log_text = f"🔍 **CEZA İTİRAZI**\n\n" \
                    f"**Ceza Türü:** {action_names[action]}\n" \
                    f"**Kullanıcı ID:** `{user_id}`\n" \
                    f"**İtiraz Sebebi:** {appeal_reason}\n" \
                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # İtiraz butonları
            approve_button = Button.inline("✅ Onayla", data=f"appeal_approve_{action}_{user_id}")
            reject_button = Button.inline("❌ Reddet", data=f"appeal_reject_{action}_{user_id}")
            
            buttons = [[approve_button, reject_button]]
            
            await log_to_thread("appeals", log_text, buttons, None)
            
            await conv.send_message("İtirazınız yöneticilere iletildi. İncelendiğinde size bildirim yapılacak.")
    except Exception as e:
        logger.error(f"İtiraz buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# İtiraz değerlendirme butonları
@client.on(events.CallbackQuery(pattern=r'appeal_(approve|reject)_(ban|mute|warn)_(\d+)'))
async def appeal_decision_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        decision = event.pattern_match.group(1).decode()
        action = event.pattern_match.group(2).decode()
        user_id = int(event.pattern_match.group(3).decode())
        
        # Yönetici kontrolü
        chat = await event.get_chat()
        if not await check_admin_permission(event, action):
            await event.answer("İtirazları değerlendirmek için yetkiniz yok.", alert=True)
            return
        
        await event.answer()
        
        try:
            appealing_user = await client.get_entity(user_id)
            
            if decision == "approve":
                # Cezayı kaldır
                if action == "ban" or action == "mute":
                    chat_id = chat.id
                    await client(EditBannedRequest(
                        chat_id,
                        user_id,
                        ChatBannedRights(
                            until_date=None,
                            view_messages=False,
                            send_messages=False,
                            send_media=False,
                            send_stickers=False,
                            send_gifs=False,
                            send_games=False,
                            send_inline=False,
                            embed_links=False
                        )
                    ))
                
                # Uyarıları temizle
                if action == "warn":
                    for group_id, group_data in config["groups"].items():
                        if "user_warnings" in group_data and str(user_id) in group_data["user_warnings"]:
                            group_data["user_warnings"][str(user_id)] = []
                    save_config(config)
                
                response_text = f"✅ **İTİRAZ ONAYLANDI**\n\n" \
                            f"**Kullanıcı:** {appealing_user.first_name} (`{user_id}`)\n" \
                            f"**Ceza Türü:** {action}\n" \
                            f"**Onaylayan:** {event.sender.first_name}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                # Kullanıcıya bildirim gönder
                try:
                    await client.send_message(user_id, f"İtirazınız onaylandı ve {action} cezanız kaldırıldı.")
                except:
                    pass
                    
            else:  # reject
                response_text = f"❌ **İTİRAZ REDDEDİLDİ**\n\n" \
                            f"**Kullanıcı:** {appealing_user.first_name} (`{user_id}`)\n" \
                            f"**Ceza Türü:** {action}\n" \
                            f"**Reddeden:** {event.sender.first_name}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                # Kullanıcıya bildirim gönder
                try:
                    await client.send_message(user_id, f"İtirazınız reddedildi ve {action} cezanız devam edecek.")
                except:
                    pass
            
            await event.edit(response_text)
            
        except Exception as e:
            await event.edit(f"İtiraz işlemi sırasında bir hata oluştu: {str(e)}")
    except Exception as e:
        logger.error(f"İtiraz değerlendirme buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# YASAKLI KELİME VE BAĞLANTI FİLTRELEME

# Yasaklı kelime ayarları
@client.on(events.NewMessage(pattern=r'/yasaklikelimeler'))
async def forbidden_words_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    if "forbidden_words" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["forbidden_words"] = []
        save_config(config)
    
    forbidden_words = config["groups"][chat_id_str]["forbidden_words"]
    
    # Menü butonları
    add_button = Button.inline("➕ Kelime Ekle", data=f"forbidden_add_{chat.id}")
    list_button = Button.inline("📋 Listeyi Göster", data=f"forbidden_list_{chat.id}")
    clear_button = Button.inline("🗑️ Listeyi Temizle", data=f"forbidden_clear_{chat.id}")
    
    buttons = [
        [add_button],
        [list_button, clear_button]
    ]
    
    await event.respond("🚫 **Yasaklı Kelimeler Menüsü**\n\nYasaklı kelimeler listesini yönetmek için bir seçenek seçin:", buttons=buttons)

# Yasaklı kelime menü işleyicileri
@client.on(events.CallbackQuery(pattern=r'forbidden_(add|list|clear)_(-?\d+)'))
async def forbidden_words_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        chat_id = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        await event.answer()
        
        if action == "add":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Eklemek istediğiniz yasaklı kelimeyi girin:")
                word_response = await conv.get_response()
                word = word_response.text.lower()
                
                if word and word not in config["groups"][chat_id_str]["forbidden_words"]:
                    config["groups"][chat_id_str]["forbidden_words"].append(word)
                    save_config(config)
                    await conv.send_message(f"'{word}' yasaklı kelimeler listesine eklendi.")
                else:
                    await conv.send_message("Bu kelime zaten listede veya geçersiz.")
        
        elif action == "list":
            forbidden_words = config["groups"][chat_id_str]["forbidden_words"]
            if forbidden_words:
                word_list = "\n".join([f"- {word}" for word in forbidden_words])
                await event.edit(f"📋 **Yasaklı Kelimeler Listesi**\n\n{word_list}")
            else:
                await event.edit("Yasaklı kelimeler listesi boş.")
        
        elif action == "clear":
            config["groups"][chat_id_str]["forbidden_words"] = []
            save_config(config)
            await event.edit("Yasaklı kelimeler listesi temizlendi.")
    except Exception as e:
        logger.error(f"Yasaklı kelime buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj filtreleme (yasaklı kelimeler ve bağlantılar)
@client.on(events.NewMessage)
async def filter_messages(event):
    # Özel mesajları kontrol etme
    if event.is_private:
        return
    
    try:
        chat = await event.get_chat()
        sender = await event.get_sender()
        chat_id_str = ensure_group_in_config(chat.id)
        
        # Yöneticileri kontrol etme - onlar filtrelenmeyecek
        is_admin = False
        try:
            participant = await client(GetParticipantRequest(chat, sender.id))
            if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                is_admin = True
        except:
            pass
        
        message = event.message
        text = message.text or message.message or ""
        
        # Yasaklı kelimeler kontrolü
        if not is_admin and "forbidden_words" in config["groups"][chat_id_str]:
            forbidden_words = config["groups"][chat_id_str]["forbidden_words"]
            for word in forbidden_words:
                if word.lower() in text.lower():
                    try:
                        await event.delete()
                        
                        # Yasaklı kelime kullanımını logla
                        log_text = f"🔤 **YASAKLI KELİME KULLANILDI**\n\n" \
                                f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                                f"**Kullanıcı:** {sender.first_name} (`{sender.id}`)\n" \
                                f"**Yasaklı Kelime:** {word}\n" \
                                f"**Mesaj:** {text}\n" \
                                f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        await log_to_thread("forbidden_words", log_text, chat.id, None)
                        return
                    except:
                        pass
        
        # Bağlantı kontrolü
        if not is_admin:
            # Telegram bağlantıları ve web bağlantıları kontrol et
            has_link = False
            
            # Metin içinde URL kontrolü
            if re.search(r'(https?://\S+|www\.\S+)', text):
                has_link = True
            
            # Telegram t.me/ bağlantıları kontrolü
            if re.search(r't\.me/[\w\+]+', text):
                has_link = True
            
            # Mesaj varlıklarında URL kontrolü
            if message.entities:
                for entity in message.entities:
                    if isinstance(entity, (MessageEntityUrl, MessageEntityTextUrl)):
                        has_link = True
                        break
            
            if has_link:
                try:
                    await event.delete()
                    
                    # Bağlantı paylaşımını logla
                    log_text = f"🔗 **YASAK BAĞLANTI PAYLAŞILDI**\n\n" \
                            f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                            f"**Kullanıcı:** {sender.first_name} (`{sender.id}`)\n" \
                            f"**Mesaj:** {text}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    await log_to_thread("forbidden_words", log_text, chat.id, None)
                except:
                    pass
    except Exception as e:
        logger.error(f"Mesaj filtreleme sırasında hata: {str(e)}")

# HOŞGELDİN MESAJLARI

# Hoşgeldin mesajı ayarları
@client.on(events.NewMessage(pattern=r'/hosgeldinmesaji'))
async def welcome_message_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    if "welcome_message" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["welcome_message"] = {
            "enabled": False,
            "text": "Gruba hoş geldiniz!",
            "buttons": []
        }
        save_config(config)
    
    welcome_settings = config["groups"][chat_id_str]["welcome_message"]
    status = "Açık ✅" if welcome_settings["enabled"] else "Kapalı ❌"
    
    # Menü butonları
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if welcome_settings['enabled'] else 'Aç 🟢'}", 
        data=f"welcome_toggle_{chat.id}"
    )
    set_text_button = Button.inline("✏️ Mesajı Değiştir", data=f"welcome_text_{chat.id}")
    add_button_button = Button.inline("➕ Buton Ekle", data=f"welcome_add_button_{chat.id}")
    clear_buttons_button = Button.inline("🗑️ Butonları Temizle", data=f"welcome_clear_buttons_{chat.id}")
    
    buttons = [
        [toggle_button],
        [set_text_button],
        [add_button_button, clear_buttons_button]
    ]
    
    welcome_text = welcome_settings["text"]
    button_info = ""
    if welcome_settings["buttons"]:
        button_info = "\n\n**Mevcut Butonlar:**\n"
        for btn in welcome_settings["buttons"]:
            button_info += f"- {btn['text']} -> {btn['url']}\n"
    
    await event.respond(
        f"👋 **Hoşgeldin Mesajı Ayarları**\n\n"
        f"**Durum:** {status}\n"
        f"**Mevcut Mesaj:**\n{welcome_text}"
        f"{button_info}",
        buttons=buttons
    )

# Hoşgeldin mesajı menü işleyicileri
@client.on(events.CallbackQuery(pattern=r'welcome_(toggle|text|add_button|clear_buttons)_(-?\d+)'))
async def welcome_settings_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        chat_id = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        await event.answer()
        
        if action == "toggle":
            config["groups"][chat_id_str]["welcome_message"]["enabled"] = not config["groups"][chat_id_str]["welcome_message"]["enabled"]
            save_config(config)
            
            status = "açıldı ✅" if config["groups"][chat_id_str]["welcome_message"]["enabled"] else "kapatıldı ❌"
            await event.edit(f"Hoşgeldin mesajı {status}")
        
        elif action == "text":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Yeni hoşgeldin mesajını girin:")
                text_response = await conv.get_response()
                new_text = text_response.text
                
                if new_text:
                    config["groups"][chat_id_str]["welcome_message"]["text"] = new_text
                    save_config(config)
                    await conv.send_message("Hoşgeldin mesajı güncellendi.")
                else:
                    await conv.send_message("Geçersiz mesaj. Değişiklik yapılmadı.")
        
        elif action == "add_button":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Buton metni girin:")
                text_response = await conv.get_response()
                button_text = text_response.text
                
                await conv.send_message("Buton URL'sini girin:")
                url_response = await conv.get_response()
                button_url = url_response.text
                
                if button_text and button_url:
                    if "buttons" not in config["groups"][chat_id_str]["welcome_message"]:
                        config["groups"][chat_id_str]["welcome_message"]["buttons"] = []
                    
                    config["groups"][chat_id_str]["welcome_message"]["buttons"].append({
                        "text": button_text,
                        "url": button_url
                    })
                    save_config(config)
                    await conv.send_message(f"Buton eklendi: {button_text} -> {button_url}")
                else:
                    await conv.send_message("Geçersiz buton bilgisi. Buton eklenemedi.")
        
        elif action == "clear_buttons":
            config["groups"][chat_id_str]["welcome_message"]["buttons"] = []
            save_config(config)
            await event.edit("Tüm butonlar temizlendi.")
    except Exception as e:
        logger.error(f"Hoşgeldin mesajı buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Hoşgeldin mesajı gönderme
# Hoşgeldin mesajı gönderme
@client.on(events.ChatAction)
async def welcome_new_users(event):
    try:
        # Sadece kullanıcı katılma olaylarını kontrol et
        if not event.user_joined and not event.user_added:
            return
        
        chat = await event.get_chat()
        chat_id_str = ensure_group_in_config(chat.id)
        user = await event.get_user()
        
        # Öncelikle giriş olayını logla
        log_text = f"👋 **YENİ ÜYE KATILDI**\n\n" \
                f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                f"**Kullanıcı:** {user.first_name} (`{user.id}`)\n" \
                f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("join_leave", log_text, chat.id, None)
        
        # Hoşgeldin mesajı etkinse gönder
        if "welcome_message" in config["groups"][chat_id_str] and config["groups"][chat_id_str]["welcome_message"]["enabled"]:
            welcome_settings = config["groups"][chat_id_str]["welcome_message"]
            
            welcome_text = welcome_settings["text"].replace("{user}", f"[{user.first_name}](tg://user?id={user.id})")
            
            # Butonları hazırla
            buttons = None
            if welcome_settings.get("buttons"):
                buttons = []
                row = []
                for i, btn in enumerate(welcome_settings["buttons"]):
                    row.append(Button.url(btn["text"], btn["url"]))
                    
                    # Her 2 butondan sonra yeni satır
                    if (i + 1) % 2 == 0 or i == len(welcome_settings["buttons"]) - 1:
                        buttons.append(row)
                        row = []
            
            # Hoşgeldin mesajını gönder
            try:
                await client.send_message(
                    chat.id,
                    welcome_text,
                    buttons=buttons,
                    parse_mode='md'
                )
            except Exception as e:
                logger.error(f"Hoşgeldin mesajı gönderilirken hata oluştu: {e}")
    except Exception as e:
        logger.error(f"Hoşgeldin mesajı işleyicisinde hata: {str(e)}")

# Çıkış olaylarını loglama - Bu fonksiyonu ayrı tutun
@client.on(events.ChatAction)
async def log_user_left(event):
    try:
        if not event.user_kicked and not event.user_left:
            return
        
        chat = await event.get_chat()
        user = await event.get_user()
        
        log_text = f"👋 **ÜYE AYRILDI**\n\n" \
                f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                f"**Kullanıcı:** {user.first_name} (`{user.id}`)\n" \
                f"**Eylem:** {'Atıldı' if event.user_kicked else 'Ayrıldı'}\n" \
                f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("join_leave", log_text, chat.id, None)
    except Exception as e:
        logger.error(f"Üye ayrılma loglamasında hata: {str(e)}")

# TEKRARLANAN MESAJLAR

# Tekrarlanan mesaj ayarları
# Aralığı metin olarak biçimlendirmek için yardımcı fonksiyon
def format_interval(seconds):
    if seconds < 60:
        return f"{seconds} saniye"
    elif seconds < 3600:
        return f"{seconds // 60} dakika"
    else:
        return f"{seconds // 3600} saat"

# Tekrarlanan mesaj ayarları menüsünü güncelleyelim
@client.on(events.NewMessage(pattern=r'/tekrarlanmesaj'))
async def repeated_messages_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    # Eğer eski yapıdaysa yeni yapıya dönüştür
    if "repeated_messages" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["repeated_messages"] = {
            "enabled": False,
            "interval": 3600,  # Varsayılan: 1 saat
            "messages": [],
            "buttons": []
        }
        save_config(config)
    
    # Eski formatı yeni formata dönüştür (eğer gerekiyorsa)
    repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
    
    # Eğer eski formatsa yeni formata dönüştür
    if "messages" in repeated_settings and isinstance(repeated_settings["messages"], list) and repeated_settings["messages"] and isinstance(repeated_settings["messages"][0], str):
        old_messages = repeated_settings["messages"]
        new_messages = []
        
        for msg in old_messages:
            new_messages.append({
                "text": msg,
                "interval": repeated_settings["interval"],
                "last_sent": 0
            })
        
        repeated_settings["messages"] = new_messages
        save_config(config)
    
    status = "Aktif ✅" if repeated_settings["enabled"] else "Devre Dışı ❌"
    
    # Ana menü butonları
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if repeated_settings['enabled'] else 'Aç 🟢'}", 
        data=f"repeated_toggle_{chat.id}"
    )
    add_message_button = Button.inline("✏️ Mesaj Ekle", data=f"repeated_add_message_{chat.id}")
    list_messages_button = Button.inline("📋 Mesajları Listele/Düzenle", data=f"repeated_list_messages_{chat.id}")
    clear_messages_button = Button.inline("🗑️ Tüm Mesajları Temizle", data=f"repeated_clear_messages_{chat.id}")
    
    # Varsayılan ayarlar butonları
    default_settings_button = Button.inline("⚙️ Varsayılan Ayarlar", data=f"repeated_default_settings_{chat.id}")
    add_button_button = Button.inline("➕ Buton Ekle", data=f"repeated_add_button_{chat.id}")
    clear_buttons_button = Button.inline("🗑️ Butonları Temizle", data=f"repeated_clear_buttons_{chat.id}")
    
    buttons = [
        [toggle_button],
        [add_message_button, list_messages_button],
        [clear_messages_button],
        [default_settings_button],
        [add_button_button, clear_buttons_button]
    ]
    
    # Mesaj sayısını hesapla
    msg_count = len(repeated_settings.get("messages", []))
    button_count = len(repeated_settings.get("buttons", []))
    
    # Varsayılan ayarları biçimlendir
    default_interval = repeated_settings.get("interval", 3600)
    if default_interval < 60:
        default_interval_text = f"{default_interval} saniye"
    elif default_interval < 3600:
        default_interval_text = f"{default_interval // 60} dakika"
    else:
        default_interval_text = f"{default_interval // 3600} saat"
    
    menu_text = f"🔄 **Tekrarlanan Mesaj Ayarları**\n\n" \
               f"**Durum:** {status}\n" \
               f"**Mesaj Sayısı:** {msg_count}\n" \
               f"**Buton Sayısı:** {button_count}\n\n" \
               f"**Varsayılan Ayarlar:**\n" \
               f"⏱️ Süre: {default_interval_text}"
    
    await event.respond(menu_text, buttons=buttons)

# Varsayılan ayarlar için yeni buton işleyici
@client.on(events.CallbackQuery(pattern=r'repeated_default_settings_(-?\d+)'))
async def repeated_default_settings_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        
        # Varsayılan değerleri al
        default_interval = repeated_settings.get("interval", 3600)
        if default_interval < 60:
            default_interval_text = f"{default_interval} saniye"
        elif default_interval < 3600:
            default_interval_text = f"{default_interval // 60} dakika"
        else:
            default_interval_text = f"{default_interval // 3600} saat"
        
        # Varsayılan ayarlar menüsü
        set_default_interval_button = Button.inline("⏱️ Varsayılan Süre Ayarla", data=f"repeated_set_default_interval_{chat_id}")
        back_button = Button.inline("⬅️ Geri", data=f"repeated_back_to_main_{chat_id}")
        
        buttons = [
            [set_default_interval_button],
            [back_button]
        ]
        
        settings_text = f"⚙️ **Varsayılan Ayarlar**\n\n" \
                      f"⏱️ **Varsayılan Süre:** {default_interval_text}\n\n" \
                      f"Bu ayarlar yeni eklenen mesajlar için kullanılacaktır."
        
        await event.edit(settings_text, buttons=buttons)
        
    except Exception as e:
        logger.error(f"Varsayılan ayarlar buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Varsayılan süre için yeni buton işleyici
@client.on(events.CallbackQuery(pattern=r'repeated_set_default_interval_(-?\d+)'))
async def repeated_default_interval_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message(
                "Varsayılan tekrarlama süresini belirtin:\n"
                "- Saat için: 1h, 2h, vb.\n"
                "- Dakika için: 1m, 30m, vb.\n"
                "- Saniye için: 30s, 45s, vb."
            )
            interval_response = await conv.get_response()
            interval_text = interval_response.text.lower()
            
            match = re.match(r'(\d+)([hms])', interval_text)
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                
                if unit == 'h':
                    seconds = value * 3600
                elif unit == 'm':
                    seconds = value * 60
                else:  # 's'
                    seconds = value
                
                config["groups"][chat_id_str]["repeated_messages"]["interval"] = seconds
                save_config(config)
                
                if seconds < 60:
                    interval_text = f"{seconds} saniye"
                elif seconds < 3600:
                    interval_text = f"{seconds // 60} dakika"
                else:
                    interval_text = f"{seconds // 3600} saat"
                
                await conv.send_message(f"Varsayılan tekrarlama süresi {interval_text} olarak ayarlandı.")
            else:
                await conv.send_message("Geçersiz format. Değişiklik yapılmadı.")
                
            # Varsayılan ayarlar menüsüne geri dön
            msg = await conv.send_message("Menüye dönülüyor...")
            await repeated_default_settings_handler(await client.get_messages(conv.chat_id, ids=msg.id))
        
    except Exception as e:
        logger.error(f"Varsayılan süre ayarlama işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Ana menüye dönüş buton işleyicisi
@client.on(events.CallbackQuery(pattern=r'repeated_back_to_main_(-?\d+)'))
async def repeated_back_to_main_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # Ana menüye dön
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Ana menüye dönüş işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj ekleme işlevini güncelle
@client.on(events.CallbackQuery(pattern=r'repeated_add_message_(-?\d+)'))
async def repeated_add_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message("Eklemek istediğiniz mesajı girin:")
            message_response = await conv.get_response()
            message_text = message_response.text
            
            if not message_text:
                await conv.send_message("Geçersiz mesaj. Değişiklik yapılmadı.")
                return
            
            # Varsayılan değerleri kullan
            default_interval = repeated_settings.get("interval", 3600)
            
            # Özel süre sorma
            await conv.send_message(
                f"Bu mesaj için tekrarlama süresini belirtin (varsayılan: {format_interval(default_interval)}):\n"
                "- Varsayılan süreyi kullanmak için 'default' yazın\n"
                "- Saat için: 1h, 2h, vb.\n"
                "- Dakika için: 1m, 30m, vb.\n"
                "- Saniye için: 30s, 45s, vb."
            )
            interval_response = await conv.get_response()
            interval_text = interval_response.text.lower()
            
            if interval_text == "default":
                interval = default_interval
            else:
                match = re.match(r'(\d+)([hms])', interval_text)
                if match:
                    value = int(match.group(1))
                    unit = match.group(2)
                    
                    if unit == 'h':
                        interval = value * 3600
                    elif unit == 'm':
                        interval = value * 60
                    else:  # 's'
                        interval = value
                else:
                    await conv.send_message("Geçersiz format. Varsayılan süre kullanılacak.")
                    interval = default_interval
            
            # Yeni mesajı ekle
            new_message = {
                "text": message_text,
                "interval": interval,
                "last_sent": 0
            }
            
            if "messages" not in repeated_settings:
                repeated_settings["messages"] = []
            
            repeated_settings["messages"].append(new_message)
            save_config(config)
            
            # Mesajın bilgilerini göster
            interval_text = format_interval(interval)
            
            await conv.send_message(
                f"Mesaj eklendi!\n\n"
                f"**Mesaj:** {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n"
                f"**Süre:** {interval_text}"
            )
            
            # Ana menüye dön
            msg = await conv.send_message("Ana menüye dönülüyor...")
            await repeated_messages_menu(await client.get_messages(conv.chat_id, ids=msg.id))
            
    except Exception as e:
        logger.error(f"Mesaj ekleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesajları listeleme ve düzenleme
@client.on(events.CallbackQuery(pattern=r'repeated_list_messages_(-?\d+)'))
async def repeated_list_messages_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if not messages:
            await event.answer("Henüz tekrarlanan mesaj eklenmemiş.", alert=True)
            return
        
        await event.answer()
        
        # Mesaj listesi ve düzenleme butonları
        message_buttons = []
        
        for i, message in enumerate(messages):
            # Mesajı kısaltıp göster
            message_text = message.get("text", "")
            if len(message_text) > 30:
                message_preview = message_text[:27] + "..."
            else:
                message_preview = message_text
                
            interval_text = format_interval(message.get("interval", 3600))
            
            # Her mesaj için düzenleme butonu
            edit_button = Button.inline(f"{i+1}. {message_preview} ({interval_text})", data=f"repeated_edit_message_{chat_id}_{i}")
            message_buttons.append([edit_button])
        
        # Geri dönüş butonu
        back_button = Button.inline("⬅️ Ana Menüye Dön", data=f"repeated_back_to_main_{chat_id}")
        message_buttons.append([back_button])
        
        await event.edit("📋 **Tekrarlanan Mesajlar**\n\nDüzenlemek istediğiniz mesajı seçin:", buttons=message_buttons)
        
    except Exception as e:
        logger.error(f"Mesaj listeleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj düzenleme
@client.on(events.CallbackQuery(pattern=r'repeated_edit_message_(-?\d+)_(\d+)'))
async def repeated_edit_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if message_index >= len(messages):
            await event.answer("Geçersiz mesaj indeksi.", alert=True)
            return
        
        message = messages[message_index]
        message_text = message.get("text", "")
        interval = message.get("interval", 3600)
        
        # Düzenleme butonları
        edit_text_button = Button.inline("✏️ Metni Düzenle", data=f"repeated_edit_text_{chat_id}_{message_index}")
        edit_interval_button = Button.inline("⏱️ Süreyi Değiştir", data=f"repeated_edit_interval_{chat_id}_{message_index}")
        delete_button = Button.inline("🗑️ Mesajı Sil", data=f"repeated_delete_message_{chat_id}_{message_index}")
        back_button = Button.inline("⬅️ Listeye Dön", data=f"repeated_list_messages_{chat_id}")
        
        buttons = [
            [edit_text_button, edit_interval_button],
            [delete_button],
            [back_button]
        ]
        
        # Mesaj bilgilerini hazırla
        interval_text = format_interval(interval)
        
        message_info = f"📝 **Mesaj Detayları**\n\n" \
                      f"**Mesaj:** {message_text}\n\n" \
                      f"**Süre:** {interval_text}"
        
        await event.edit(message_info, buttons=buttons)
        
    except Exception as e:
        logger.error(f"Mesaj düzenleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj metnini düzenleme
@client.on(events.CallbackQuery(pattern=r'repeated_edit_text_(-?\d+)_(\d+)'))
async def repeated_edit_text_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if message_index >= len(messages):
            await event.answer("Geçersiz mesaj indeksi.", alert=True)
            return
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            current_message = messages[message_index]
            
            await conv.send_message(f"Mevcut mesaj:\n\n{current_message.get('text', '')}\n\nYeni mesajı girin:")
            message_response = await conv.get_response()
            new_text = message_response.text
            
            if new_text:
                messages[message_index]["text"] = new_text
                save_config(config)
                await conv.send_message("Mesaj metni güncellendi.")
            else:
                await conv.send_message("Geçersiz mesaj. Değişiklik yapılmadı.")
            
            # Mesaj düzenleme menüsüne geri dön
            msg = await conv.send_message("Düzenleme menüsüne dönülüyor...")
            fake_event = await client.get_messages(conv.chat_id, ids=msg.id)
            fake_event.pattern_match = re.match(r'repeated_edit_message_(-?\d+)_(\d+)', f"repeated_edit_message_{chat_id}_{message_index}")
            await repeated_edit_message_handler(fake_event)
            
    except Exception as e:
        logger.error(f"Mesaj metni düzenleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj süresini düzenleme
@client.on(events.CallbackQuery(pattern=r'repeated_edit_interval_(-?\d+)_(\d+)'))
async def repeated_edit_interval_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if message_index >= len(messages):
            await event.answer("Geçersiz mesaj indeksi.", alert=True)
            return
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            current_message = messages[message_index]
            current_interval = current_message.get("interval", 3600)
            current_interval_text = format_interval(current_interval)
            
            await conv.send_message(
                f"Mevcut süre: {current_interval_text}\n\n"
                "Yeni tekrarlama süresini belirtin:\n"
                "- Saat için: 1h, 2h, vb.\n"
                "- Dakika için: 1m, 30m, vb.\n"
                "- Saniye için: 30s, 45s, vb."
            )
            interval_response = await conv.get_response()
            interval_text = interval_response.text.lower()
            
            match = re.match(r'(\d+)([hms])', interval_text)
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                
                if unit == 'h':
                    seconds = value * 3600
                elif unit == 'm':
                    seconds = value * 60
                else:  # 's'
                    seconds = value
                
                messages[message_index]["interval"] = seconds
                save_config(config)
                
                await conv.send_message(f"Mesaj süresi {format_interval(seconds)} olarak güncellendi.")
            else:
                await conv.send_message("Geçersiz format. Değişiklik yapılmadı.")
            
            # Mesaj düzenleme menüsüne geri dön
            msg = await conv.send_message("Düzenleme menüsüne dönülüyor...")
            fake_event = await client.get_messages(conv.chat_id, ids=msg.id)
            fake_event.pattern_match = re.match(r'repeated_edit_message_(-?\d+)_(\d+)', f"repeated_edit_message_{chat_id}_{message_index}")
            await repeated_edit_message_handler(fake_event)
            
    except Exception as e:
        logger.error(f"Mesaj süresi düzenleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj silme
@client.on(events.CallbackQuery(pattern=r'repeated_delete_message_(-?\d+)_(\d+)'))
async def repeated_delete_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if message_index >= len(messages):
            await event.answer("Geçersiz mesaj indeksi.", alert=True)
            return
        
        # Onay iste
        confirm_button = Button.inline("✅ Evet, Sil", data=f"repeated_confirm_delete_message_{chat_id}_{message_index}")
        cancel_button = Button.inline("❌ İptal", data=f"repeated_edit_message_{chat_id}_{message_index}")
        
        buttons = [
            [confirm_button],
            [cancel_button]
        ]
        
        message_text = messages[message_index].get("text", "")
        if len(message_text) > 50:
            message_preview = message_text[:47] + "..."
        else:
            message_preview = message_text
            
        await event.edit(
            f"⚠️ **Mesajı Silmek İstiyor musunuz?**\n\n"
            f"**Mesaj:** {message_preview}\n\n"
            f"Bu işlem geri alınamaz!",
            buttons=buttons
        )
        
    except Exception as e:
        logger.error(f"Mesaj silme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj silme onayı
@client.on(events.CallbackQuery(pattern=r'repeated_confirm_delete_message_(-?\d+)_(\d+)'))
async def repeated_confirm_delete_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if message_index >= len(messages):
            await event.answer("Geçersiz mesaj indeksi.", alert=True)
            return
        
        # Mesajı sil
        deleted_message = messages.pop(message_index)
        save_config(config)
        
        deleted_text = deleted_message.get("text", "")
        if len(deleted_text) > 30:
            deleted_preview = deleted_text[:27] + "..."
        else:
            deleted_preview = deleted_text
        
        await event.answer(f"Mesaj silindi: {deleted_preview}")
        
        # Mesaj listesine geri dön
        await repeated_list_messages_handler(event)
        
    except Exception as e:
        logger.error(f"Mesaj silme onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tüm mesajları temizle
@client.on(events.CallbackQuery(pattern=r'repeated_clear_messages_(-?\d+)'))
async def repeated_clear_messages_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        messages = repeated_settings.get("messages", [])
        
        if not messages:
            await event.answer("Silinecek mesaj bulunamadı.", alert=True)
            return
            
        # Onay iste
        confirm_button = Button.inline("✅ Evet, Tümünü Sil", data=f"repeated_confirm_clear_messages_{chat_id}")
        cancel_button = Button.inline("❌ İptal", data=f"repeated_back_to_main_{chat_id}")
        
        buttons = [
            [confirm_button],
            [cancel_button]
        ]
        
        await event.edit(
            f"⚠️ **UYARI**\n\n"
            f"Toplam {len(messages)} adet tekrarlanan mesajı silmek istediğinize emin misiniz?\n"
            f"Bu işlem geri alınamaz!",
            buttons=buttons
        )
        
    except Exception as e:
        logger.error(f"Mesajları temizleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tüm mesajları temizleme onayı
@client.on(events.CallbackQuery(pattern=r'repeated_confirm_clear_messages_(-?\d+)'))
async def repeated_confirm_clear_messages_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        # Tüm mesajları temizle
        config["groups"][chat_id_str]["repeated_messages"]["messages"] = []
        save_config(config)
        
        await event.answer("Tüm tekrarlanan mesajlar silindi.")
        
        # Ana menüye dön
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Mesajları temizleme onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Buton ekleme için düzeltilmiş kod
@client.on(events.CallbackQuery(pattern=r'repeated_add_button_(-?\d+)'))
async def repeated_add_button_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message("Buton metni girin:")
            text_response = await conv.get_response()
            button_text = text_response.text
            
            if not button_text:
                await conv.send_message("Geçersiz buton metni. İşlem iptal edildi.")
                return
            
            await conv.send_message("Buton URL'sini girin (örn. https://example.com):")
            url_response = await conv.get_response()
            button_url = url_response.text
            
            # URL'nin geçerli olduğundan emin ol
            if not button_url.startswith(('http://', 'https://', 't.me/')):
                await conv.send_message("Geçersiz URL. URL 'http://', 'https://' veya 't.me/' ile başlamalıdır. İşlem iptal edildi.")
                return
            
            # Butonları hazırla
            if "buttons" not in repeated_settings:
                repeated_settings["buttons"] = []
            
            repeated_settings["buttons"].append({
                "text": button_text,
                "url": button_url
            })
            save_config(config)
            
            await conv.send_message(f"Buton eklendi:\n**Metin:** {button_text}\n**URL:** {button_url}")
            
            # Ana menüye dön
            msg = await conv.send_message("Ana menüye dönülüyor...")
            await repeated_messages_menu(await client.get_messages(conv.chat_id, ids=msg.id))
    
    except Exception as e:
        logger.error(f"Buton ekleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Butonları temizleme işlevi
@client.on(events.CallbackQuery(pattern=r'repeated_clear_buttons_(-?\d+)'))
async def repeated_clear_buttons_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        buttons = config["groups"][chat_id_str]["repeated_messages"].get("buttons", [])
        
        if not buttons:
            await event.answer("Silinecek buton bulunamadı.", alert=True)
            return
        
        # Onay iste
        confirm_button = Button.inline("✅ Evet, Tüm Butonları Sil", data=f"repeated_confirm_clear_buttons_{chat_id}")
        cancel_button = Button.inline("❌ İptal", data=f"repeated_back_to_main_{chat_id}")
        
        buttons = [
            [confirm_button],
            [cancel_button]
        ]
        
        await event.edit(
            f"⚠️ **UYARI**\n\n"
            f"Tüm butonları silmek istediğinize emin misiniz?\n"
            f"Bu işlem geri alınamaz!",
            buttons=buttons
        )
        
    except Exception as e:
        logger.error(f"Butonları temizleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Butonları temizleme onayı
@client.on(events.CallbackQuery(pattern=r'repeated_confirm_clear_buttons_(-?\d+)'))
async def repeated_confirm_clear_buttons_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        # Tüm butonları temizle
        config["groups"][chat_id_str]["repeated_messages"]["buttons"] = []
        save_config(config)
        
        await event.answer("Tüm butonlar silindi.")
        
        # Ana menüye dön
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Butonları temizleme onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tekrarlanan mesajları gönderme işlevini güncelle
async def send_repeated_messages():
    while True:
        try:
            current_time = time.time()
            
            for chat_id_str, group_data in config["groups"].items():
                if "repeated_messages" in group_data:
                    repeated_settings = group_data["repeated_messages"]
                    
                    # Sistem devre dışıysa kontrol etme
                    if not repeated_settings.get("enabled", False):
                        continue
                    
                    chat_id = int(chat_id_str)
                    messages = repeated_settings.get("messages", [])
                    buttons = repeated_settings.get("buttons", [])
                    
                    # Her mesajı ayrı ayrı kontrol et
                    for i, message in enumerate(messages):
                        # ÖNEMLİ: Eski format mesajları kontrol et ve dönüştür
                        if isinstance(message, str):
                            # Eski formatı yeni formata dönüştür
                            old_message_text = message
                            messages[i] = {
                                "text": old_message_text,
                                "interval": repeated_settings.get("interval", 3600),
                                "last_sent": 0
                            }
                            save_config(config)
                            message = messages[i]  # Güncellenmiş mesajı al
                        
                        # Artık her mesaj dict formatında olmalı
                        message_text = message["text"]
                        interval = message.get("interval", 3600)
                        last_sent = message.get("last_sent", 0)
                        
                        # Gönderme zamanı geldiyse
                        if current_time - last_sent >= interval:
                            try:
                                # Butonları hazırla
                                message_buttons = None
                                if buttons:
                                    btn_array = []
                                    row = []
                                    for j, btn in enumerate(buttons):
                                        row.append(Button.url(btn["text"], btn["url"]))
                                        
                                        # Her 2 butondan sonra yeni satır
                                        if (j + 1) % 2 == 0 or j == len(buttons) - 1:
                                            btn_array.append(row)
                                            row = []
                                    
                                    if btn_array:
                                        message_buttons = btn_array
                                
                                # Normal metin mesajı
                                await client.send_message(
                                    chat_id,
                                    message_text,
                                    buttons=message_buttons
                                )
                                
                                # Son gönderim zamanını güncelle
                                messages[i]["last_sent"] = current_time
                                save_config(config)
                                
                                # Tekrarlanan mesajı logla
                                log_text = f"🔄 **TEKRARLANAN MESAJ GÖNDERİLDİ**\n\n" \
                                        f"**Grup ID:** `{chat_id}`\n" \
                                        f"**Mesaj:** {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n" \
                                        f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                
                                await log_to_thread("repeated_msgs", log_text, chat.id, None)
                                
                            except Exception as e:
                                logger.error(f"Tekrarlanan mesaj gönderilirken hata oluştu: {e}")
            
        except Exception as e:
            logger.error(f"Tekrarlanan mesaj döngüsünde hata oluştu: {e}")
        
        # Her 30 saniyede bir kontrol et
        await asyncio.sleep(30)

# YÖNETİCİ YETKİLERİ

# Yetki verme komutu
@client.on(events.NewMessage(pattern=r'/yetkiver(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def grant_permission(event):
    if not await check_admin_permission(event, "add_admin"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    permission_type = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Yetki vermek için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    valid_permissions = ["ban", "mute", "kick", "warn", "edit_group"]
    
    if not permission_type:
        permission_list = ", ".join(valid_permissions)
        await event.respond(f"Lütfen bir yetki türü belirtin. Geçerli yetkiler: {permission_list}")
        return
    
    permission_type = permission_type.strip().lower()
    
    if permission_type not in valid_permissions:
        permission_list = ", ".join(valid_permissions)
        await event.respond(f"Geçersiz yetki türü. Geçerli yetkiler: {permission_list}")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    if "admin_permissions" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["admin_permissions"] = {}
    
    user_id_str = str(user_id)
    if user_id_str not in config["groups"][chat_id_str]["admin_permissions"]:
        config["groups"][chat_id_str]["admin_permissions"][user_id_str] = []
    
    if permission_type not in config["groups"][chat_id_str]["admin_permissions"][user_id_str]:
        config["groups"][chat_id_str]["admin_permissions"][user_id_str].append(permission_type)
        save_config(config)
        
        try:
            user = await client.get_entity(user_id)
            permission_names = {
                "ban": "Banlama",
                "mute": "Susturma",
                "kick": "Atma",
                "warn": "Uyarma",
                "edit_group": "Grup Düzenleme"
            }
            
            await event.respond(f"Kullanıcı {user.first_name} için {permission_names[permission_type]} yetkisi verildi.")
            
            # Yetki değişikliğini logla
            log_text = f"👮 **YETKİ VERİLDİ**\n\n" \
                    f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                    f"**Veren Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                    f"**Yetki:** {permission_names[permission_type]}\n" \
                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await log_to_thread("join_leave", log_text, chat.id, None)  # Özel bir log thread'i oluşturulabilir
            
        except Exception as e:
            await event.respond(f"Bir hata oluştu: {str(e)}")
    else:
        await event.respond("Bu kullanıcının zaten bu yetkisi var.")

# Yetki alma komutu
@client.on(events.NewMessage(pattern=r'/yetkial(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
async def revoke_permission(event):
    if not await check_admin_permission(event, "add_admin"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    permission_type = event.pattern_match.group(2)
    
    if not args:
        if event.reply_to:
            user_id = (await event.get_reply_message()).sender_id
        else:
            await event.respond("Yetki almak için bir kullanıcıya yanıt verin veya kullanıcı adı/ID belirtin.")
            return
    else:
        args = args.strip()
        if args.startswith('@'):
            try:
                user = await client.get_entity(args)
                user_id = user.id
            except:
                await event.respond("Belirtilen kullanıcı bulunamadı.")
                return
        else:
            try:
                user_id = int(args)
            except ValueError:
                await event.respond("Geçersiz kullanıcı ID formatı.")
                return
    
    valid_permissions = ["ban", "mute", "kick", "warn", "edit_group"]
    
    if not permission_type:
        permission_list = ", ".join(valid_permissions)
        await event.respond(f"Lütfen bir yetki türü belirtin. Geçerli yetkiler: {permission_list}")
        return
    
    permission_type = permission_type.strip().lower()
    
    if permission_type not in valid_permissions:
        permission_list = ", ".join(valid_permissions)
        await event.respond(f"Geçersiz yetki türü. Geçerli yetkiler: {permission_list}")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    user_id_str = str(user_id)
    if "admin_permissions" in config["groups"][chat_id_str] and \
       user_id_str in config["groups"][chat_id_str]["admin_permissions"] and \
       permission_type in config["groups"][chat_id_str]["admin_permissions"][user_id_str]:
        
        config["groups"][chat_id_str]["admin_permissions"][user_id_str].remove(permission_type)
        
        # Eğer kullanıcının hiç yetkisi kalmadıysa listeden çıkar
        if not config["groups"][chat_id_str]["admin_permissions"][user_id_str]:
            del config["groups"][chat_id_str]["admin_permissions"][user_id_str]
        
        save_config(config)
        
        try:
            user = await client.get_entity(user_id)
            permission_names = {
                "ban": "Banlama",
                "mute": "Susturma",
                "kick": "Atma",
                "warn": "Uyarma",
                "edit_group": "Grup Düzenleme"
            }
            
            await event.respond(f"Kullanıcı {user.first_name} için {permission_names[permission_type]} yetkisi alındı.")
            
            # Yetki değişikliğini logla
            log_text = f"👮 **YETKİ ALINDI**\n\n" \
                    f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                    f"**Alan Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                    f"**Yetki:** {permission_names[permission_type]}\n" \
                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await log_to_thread("join_leave", log_text, chat.id, None)  # Özel bir log thread'i oluşturulabilir
            
        except Exception as e:
            await event.respond(f"Bir hata oluştu: {str(e)}")
    else:
        await event.respond("Bu kullanıcıda bu yetki zaten yok.")

# UYARI AYARLARI

# Uyarı ayarları
@client.on(events.NewMessage(pattern=r'/uyariayarlari'))
async def warn_settings_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    if "warn_settings" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["warn_settings"] = {
            "max_warns": 3,
            "action": "ban",  # veya "mute"
            "mute_duration": 24  # saat
        }
        save_config(config)
    
    warn_settings = config["groups"][chat_id_str]["warn_settings"]
    
    # Menü butonları
    set_max_button = Button.inline("🔢 Maksimum Uyarı", data=f"warn_max_{chat.id}")
    set_action_button = Button.inline(
        f"🔄 Eylem: {'Ban' if warn_settings['action'] == 'ban' else 'Mute'}", 
        data=f"warn_action_{chat.id}"
    )
    set_duration_button = Button.inline("⏱️ Mute Süresi", data=f"warn_duration_{chat.id}")
    
    buttons = [
        [set_max_button],
        [set_action_button],
        [set_duration_button]
    ]
    
    action_text = "Ban" if warn_settings["action"] == "ban" else f"Mute ({warn_settings['mute_duration']} saat)"
    
    await event.respond(
        f"⚠️ **Uyarı Ayarları**\n\n"
        f"**Maksimum Uyarı:** {warn_settings['max_warns']}\n"
        f"**Eylem:** {action_text}",
        buttons=buttons
    )

# Uyarı ayarları menü işleyicileri
@client.on(events.CallbackQuery(pattern=r'warn_(max|action|duration)_(-?\d+)'))
async def warn_settings_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        chat_id = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        await event.answer()
        
        if action == "max":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Maksimum uyarı sayısını girin (1-10):")
                max_response = await conv.get_response()
                
                try:
                    max_warns = int(max_response.text)
                    if 1 <= max_warns <= 10:
                        config["groups"][chat_id_str]["warn_settings"]["max_warns"] = max_warns
                        save_config(config)
                        await conv.send_message(f"Maksimum uyarı sayısı {max_warns} olarak ayarlandı.")
                    else:
                        await conv.send_message("Geçersiz değer. 1 ile 10 arasında bir sayı girin.")
                except ValueError:
                    await conv.send_message("Geçersiz değer. Lütfen bir sayı girin.")
        
        elif action == "action":
            current_action = config["groups"][chat_id_str]["warn_settings"]["action"]
            new_action = "mute" if current_action == "ban" else "ban"
            
            config["groups"][chat_id_str]["warn_settings"]["action"] = new_action
            save_config(config)
            
            action_text = "Ban" if new_action == "ban" else "Mute"
            await event.edit(f"Uyarı eylem türü '{action_text}' olarak değiştirildi.")
        
        elif action == "duration":
            if config["groups"][chat_id_str]["warn_settings"]["action"] != "mute":
                await event.edit("Bu ayar sadece eylem türü 'Mute' olduğunda geçerlidir.")
                return
            
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Mute süresini saat cinsinden girin (1-168):")
                duration_response = await conv.get_response()
                
                try:
                    duration = int(duration_response.text)
                    if 1 <= duration <= 168:  # 1 saat - 1 hafta
                        config["groups"][chat_id_str]["warn_settings"]["mute_duration"] = duration
                        save_config(config)
                        await conv.send_message(f"Mute süresi {duration} saat olarak ayarlandı.")
                    else:
                        await conv.send_message("Geçersiz değer. 1 ile 168 (1 hafta) arasında bir sayı girin.")
                except ValueError:
                    await conv.send_message("Geçersiz değer. Lütfen bir sayı girin.")
    except Exception as e:
        logger.error(f"Uyarı ayarları buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Yardım komutu
@client.on(events.NewMessage(pattern=r'/yardim|/help'))
async def help_command(event):
    help_text = """🤖 **Moderasyon Bot Komutları** 🤖

**👮‍♂️ Moderasyon Komutları:**
/ban <kullanıcı> <sebep> - Kullanıcıyı yasaklar
/unban <kullanıcı> <sebep> - Kullanıcının yasağını kaldırır
/mute <kullanıcı> [süre] <sebep> - Kullanıcıyı susturur
/unmute <kullanıcı> <sebep> - Kullanıcının susturmasını kaldırır
/kick <kullanıcı> <sebep> - Kullanıcıyı gruptan atar
/warn <kullanıcı> <sebep> - Kullanıcıyı uyarır
/unwarn <kullanıcı> <sebep> - Kullanıcının son uyarısını kaldırır
/info <kullanıcı> - Kullanıcı hakkında bilgi verir

**⚙️ Yapılandırma Komutları:**
/yasaklikelimeler - Yasaklı kelimeler menüsünü açar
/hosgeldinmesaji - Hoşgeldin mesajı ayarları
/tekrarlanmesaj - Tekrarlanan mesaj ayarları
/uyariayarlari - Uyarı sistemi ayarları
/logayarlari - Log kanalı ve thread ayarları
/antiflood - Anti-flood ayarları

**👮‍♂️ Yönetici Komutları:**
/yetkiver <kullanıcı> <yetki> - Kullanıcıya özel yetki verir
/yetkial <kullanıcı> <yetki> - Kullanıcıdan yetkiyi alır

**ℹ️ Diğer Komutlar:**
/yardim - Bu mesajı gösterir
/stat - Grup istatistiklerini gösterir

📢 Tüm moderasyon işlemleri otomatik olarak loglanır.
⚠️ Moderasyon komutları için sebep belirtmek zorunludur.
"""
    
    await event.respond(help_text)


# Log ayarları komutu
@client.on(events.NewMessage(pattern=r'/logayarlari'))
async def log_settings_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    # Eğer log ayarları yoksa varsayılanları ekle
    if "log_settings" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["log_settings"] = {
            "enabled": False,
            "log_channel_id": 0,
            "thread_ids": {
                "ban": 0,
                "mute": 0,
                "forbidden_words": 0,
                "join_leave": 0,
                "kicks": 0,
                "warns": 0,
                "voice_chats": 0,
                "repeated_msgs": 0,
                "appeals": 0,
                "stats": 0
            }
        }
        save_config(config)
    
    log_settings = config["groups"][chat_id_str]["log_settings"]
    status = "Aktif ✅" if log_settings["enabled"] else "Devre Dışı ❌"
    
    # Ana menü butonları
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if log_settings['enabled'] else 'Aç 🟢'}", 
        data=f"log_toggle_{chat.id}"
    )
    set_channel_button = Button.inline("📊 Log Kanalı Ayarla", data=f"log_channel_{chat.id}")
    thread_ids_button = Button.inline("🧵 Thread ID'leri Ayarla", data=f"log_threads_{chat.id}")
    
    buttons = [
        [toggle_button],
        [set_channel_button],
        [thread_ids_button]
    ]
    
    # Mevcut log kanalı bilgisini göster
    channel_info = "Ayarlanmadı" if log_settings["log_channel_id"] == 0 else f"`{log_settings['log_channel_id']}`"
    
    menu_text = f"📝 **Log Ayarları**\n\n" \
               f"**Durum:** {status}\n" \
               f"**Log Kanalı:** {channel_info}\n\n" \
               f"Log ayarlarını düzenlemek için butonları kullanın."
    
    await event.respond(menu_text, buttons=buttons)

# Log ayarları durumunu değiştirme
@client.on(events.CallbackQuery(pattern=r'log_toggle_(-?\d+)'))
async def log_toggle_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        log_settings = config["groups"][chat_id_str]["log_settings"]
        
        # Log kanalı ayarlanmamışsa uyarı ver
        if log_settings["log_channel_id"] == 0 and not log_settings["enabled"]:
            await event.answer("Önce bir log kanalı ayarlayın!", alert=True)
            return
            
        # Durumu değiştir
        log_settings["enabled"] = not log_settings["enabled"]
        save_config(config)
        
        status = "aktif ✅" if log_settings["enabled"] else "devre dışı ❌"
        await event.answer(f"Log sistemi {status} olarak ayarlandı.")
        
        # Menüyü güncelle
        await log_settings_menu(event)
        
    except Exception as e:
        logger.error(f"Log durumu değiştirirken hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Log kanalı ayarlama
@client.on(events.CallbackQuery(pattern=r'log_channel_(-?\d+)'))
async def log_channel_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message(
                "Log kanalının ID'sini girin:\n\n"
                "1. Bot'u log kanalına ekleyin\n"
                "2. Log kanalında bir mesaj gönderin\n"
                "3. Bu mesajı size iletilen bot mesajından alın\n"
                "4. Buraya girin (örn. -1001234567890)"
            )
            
            response = await conv.get_response()
            try:
                channel_id = int(response.text.strip())
                
                # Kanalı doğrula
                try:
                    channel = await client.get_entity(channel_id)
                    
                    # Botun kanala mesaj gönderme yetkisini kontrol et
                    await client.send_message(
                        channel_id,
                        "✅ **Log Kanalı Kurulumu**\n\n"
                        "Bu kanal artık log kanalı olarak ayarlandı.\n"
                        "Bu mesaj, botun bu kanala mesaj gönderebilme yetkisini doğrulamak için gönderilmiştir."
                    )
                    
                    # Kanalı ayarla
                    config["groups"][chat_id_str]["log_settings"]["log_channel_id"] = channel_id
                    save_config(config)
                    
                    await conv.send_message(f"Log kanalı başarıyla ayarlandı. Kanal: {channel.title}")
                except Exception as e:
                    await conv.send_message(f"Kanal ayarlanamadı: {str(e)}\nBot'un kanala eklendiğinden ve mesaj gönderme yetkisine sahip olduğundan emin olun.")
            except ValueError:
                await conv.send_message("Geçersiz kanal ID'si. Sayısal bir değer girin.")
            
            # Menüye dön
            msg = await conv.send_message("Menüye dönülüyor...")
            await log_settings_menu(await client.get_messages(conv.chat_id, ids=msg.id))
        
    except Exception as e:
        logger.error(f"Log kanalı ayarlanırken hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Thread ID'leri ayarlama menüsü
@client.on(events.CallbackQuery(pattern=r'log_threads_(-?\d+)'))
async def log_threads_menu_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        log_settings = config["groups"][chat_id_str]["log_settings"]
        
        # Log kanalı ayarlanmamışsa uyarı ver
        if log_settings["log_channel_id"] == 0:
            await event.answer("Önce bir log kanalı ayarlayın!", alert=True)
            return
        
        # Thread türleri ve açıklamaları
        thread_types = {
            "ban": "Ban İşlemleri 🚫",
            "mute": "Susturma İşlemleri 🔇",
            "forbidden_words": "Yasaklı Kelimeler 🔤",
            "join_leave": "Katılma/Ayrılma 👋",
            "kicks": "Atma İşlemleri 👢",
            "warns": "Uyarı İşlemleri ⚠️",
            "voice_chats": "Sesli Sohbet 🎙️",
            "repeated_msgs": "Tekrarlanan Mesajlar 🔄",
            "appeals": "İtirazlar 🙋‍♂️",
            "stats": "İstatistikler 📊"
        }
        
        # Thread ayarlama butonları
        buttons = []
        for thread_type, description in thread_types.items():
            current_id = log_settings["thread_ids"].get(thread_type, 0)
            status = "✅" if current_id != 0 else "❌"
            buttons.append([Button.inline(f"{description} {status}", data=f"log_set_thread_{chat_id}_{thread_type}")])
        
        # Geri dönüş butonu
        buttons.append([Button.inline("⬅️ Geri", data=f"log_back_to_main_{chat_id}")])
        
        await event.edit("🧵 **Thread ID Ayarları**\n\nAyarlamak istediğiniz thread türünü seçin:", buttons=buttons)
        
    except Exception as e:
        logger.error(f"Thread menüsü açılırken hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Thread ID ayarlama
@client.on(events.CallbackQuery(pattern=r'log_set_thread_(-?\d+)_(.+)'))
async def log_set_thread_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        thread_type = event.pattern_match.group(2).decode()
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            thread_descriptions = {
                "ban": "Ban İşlemleri 🚫",
                "mute": "Susturma İşlemleri 🔇",
                "forbidden_words": "Yasaklı Kelimeler 🔤",
                "join_leave": "Katılma/Ayrılma 👋",
                "kicks": "Atma İşlemleri 👢",
                "warns": "Uyarı İşlemleri ⚠️",
                "voice_chats": "Sesli Sohbet 🎙️",
                "repeated_msgs": "Tekrarlanan Mesajlar 🔄",
                "appeals": "İtirazlar 🙋‍♂️",
                "stats": "İstatistikler 📊"
            }
            
            description = thread_descriptions.get(thread_type, thread_type)
            
            await conv.send_message(
                f"**{description}** için Thread ID'sini ayarlayın:\n\n"
                "1. Log kanalında yeni bir konu başlatın\n"
                "2. O konuya bir mesaj gönderin\n"
                "3. Mesajı botunuza iletin\n"
                "4. Thread ID'yi buraya yazın veya\n"
                "5. Devre dışı bırakmak için 0 yazın"
            )
            
            response = await conv.get_response()
            try:
                thread_id = int(response.text.strip())
                
                # Thread ID'yi ayarla
                config["groups"][chat_id_str]["log_settings"]["thread_ids"][thread_type] = thread_id
                save_config(config)
                
                if thread_id == 0:
                    await conv.send_message(f"**{description}** için thread devre dışı bırakıldı.")
                else:
                    # Thread'e test mesajı gönder
                    try:
                        channel_id = config["groups"][chat_id_str]["log_settings"]["log_channel_id"]
                        await client.send_message(
                            channel_id,
                            f"✅ **Thread Testi**\n\nBu mesaj **{description}** thread'inin doğru çalıştığını kontrol etmek için gönderilmiştir.",
                            reply_to=thread_id
                        )
                        await conv.send_message(f"**{description}** için thread ID başarıyla ayarlandı.")
                    except Exception as e:
                        await conv.send_message(f"Thread ID ayarlandı ancak test mesajı gönderilemedi: {str(e)}")
            except ValueError:
                await conv.send_message("Geçersiz Thread ID. Sayısal bir değer girin.")
            
            # Thread menüsüne dön
            msg = await conv.send_message("Thread menüsüne dönülüyor...")
            fake_event = await client.get_messages(conv.chat_id, ids=msg.id)
            fake_event.pattern_match = re.match(r'log_threads_(-?\d+)', f"log_threads_{chat_id}")
            await log_threads_menu_handler(fake_event)
        
    except Exception as e:
        logger.error(f"Thread ID ayarlanırken hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Ana menüye dönüş
@client.on(events.CallbackQuery(pattern=r'log_back_to_main_(-?\d+)'))
async def log_back_to_main_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # Ana menüye dön
        await log_settings_menu(event)
        
    except Exception as e:
        logger.error(f"Ana menüye dönüş işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)
# Ana fonksiyon
async def main():
    load_stats()
    # Tekrarlanan mesajlar için arka plan görevi
    asyncio.create_task(send_repeated_messages())
    asyncio.create_task(send_daily_report())
    print("Bot çalışıyor!")
    
    # Bot sonsuza kadar çalışsın
    await client.run_until_disconnected()

# Bot'u başlat
with client:
    client.loop.run_until_complete(main())
