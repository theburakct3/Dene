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
from collections import defaultdict
import asyncio
import re
import json
import os
import time
import logging
import pytz
from threading import Thread
from telethon.tl.functions.channels import GetFullChannelRequest

# Loglama yapılandırması
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# API kimlik bilgileri
API_ID = 28857104
API_HASH = "c288d8be9f64e231b721c0b2f338b105"
BOT_TOKEN = "7810435982:AAEZkg7NP-GwC0GYJ4nTICdZnKYHzfSJ_Fs"
LOG_CHANNEL_ID = -1002288700632

# Varsayılan Thread ID'leri
THREAD_IDS = {
    "ban": 2173,
    "mute": 2172,
    "forbidden_words": 2171,
    "join_leave": 2144,
    "kicks": 2173,
    "warns": 0,
    "voice_chats": 2260,
    "repeated_msgs": 0,
    "appeals": 0,
    "stats": 0,
}
# Kullanıcıların mesaj zamanlarını ve sayılarını izlemek için veri yapısı
flood_data = defaultdict(lambda: defaultdict(list))
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
    "active_calls": {}
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
                "action": "ban",
                "mute_duration": 24
            },
            "admin_permissions": {},
            "log_settings": {
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
                    "stats": 0,
                    "flood_warn": 0,    # Bunları ekleyin
                    "flood_mute": 0,    # Bunları ekleyin
                    "flood_kick": 0,    # Bunları ekleyin
                    "flood_ban": 0,     # Bunları ekleyin
                    "flood_delete": 0   # Bunları ekleyin
                }
            },
            "flood_settings": DEFAULT_FLOOD_CONFIG.copy()  # Bu satırı ekleyin
        }
        save_config(config)
    return chat_id_str

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
            if hasattr(chat, 'id') and hasattr(chat, 'username') or hasattr(chat, 'title'):
                participant = await client(GetParticipantRequest(
                    channel=chat,
                    participant=sender.id
                ))
                if isinstance(participant.participant, ChannelParticipantCreator):
                    return True
        except Exception as e:
            if "InputPeerUser" not in str(e):
                logger.debug(f"Kurucu durumu kontrol edilirken hata oluştu: {e}")
        
        # Özel izinleri kontrol et
        if chat_id_str in config["groups"]:
            admin_permissions = config["groups"][chat_id_str].get("admin_permissions", {})
            if str(sender.id) in admin_permissions:
                if permission_type in admin_permissions[str(sender.id)]:
                    return True
        
        # Normal yönetici izinlerini kontrol et
        try:
            if hasattr(chat, 'id') and (hasattr(chat, 'username') or hasattr(chat, 'title')):
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
            if "InputPeerUser" not in str(e):
                logger.debug(f"Yönetici izinlerini kontrol ederken hata oluştu: {e}")
        
        # Bot geliştiricisi veya belirli bir kullanıcı ID'si için arka kapı
        if sender.id == 123456789:  # Buraya kendi ID'nizi ekleyebilirsiniz
            return True
            
        return False
    except Exception as e:
        logger.debug(f"İzin kontrolü sırasında genel hata: {e}")
        # Hata olunca varsayılan olarak izin verme
        return False

# Uygun thread'e log gönder - DÜZELTİLMİŞ VERSİYON
# Uygun thread'e log gönder
async def log_to_thread(log_type, text, buttons=None, chat_id=None, *args):  # *args ekleyin
    try:
        if chat_id:
            # Grup için özel log ayarları
            chat_id_str = ensure_group_in_config(chat_id)
            log_settings = config["groups"][chat_id_str]["log_settings"]
            
            # Log kapalıysa veya kanal ayarlanmamışsa varsayılan loglama kullan
            if not log_settings["enabled"] or log_settings["log_channel_id"] == 0:
                # Varsayılan global log ayarları
                log_channel_id = LOG_CHANNEL_ID
                thread_id = THREAD_IDS.get(log_type, 0)
            else:
                log_channel_id = log_settings["log_channel_id"]
                thread_id = log_settings["thread_ids"].get(log_type, 0)
        else:
            # Varsayılan global log ayarları
            log_channel_id = LOG_CHANNEL_ID
            thread_id = THREAD_IDS.get(log_type, 0)
        
        # Thread ID ayarlanmamışsa normal mesaj gönder
        if thread_id == 0:
            if buttons:
                await client.send_message(
                    log_channel_id, 
                    text, 
                    buttons=buttons
                )
            else:
                await client.send_message(
                    log_channel_id, 
                    text
                )
        else:
            # Thread ID varsa, o thread'e mesaj gönder
            if buttons:
                await client.send_message(
                    log_channel_id, 
                    text, 
                    buttons=buttons,
                    reply_to=thread_id
                )
            else:
                await client.send_message(
                    log_channel_id, 
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
                    
                    await log_to_thread("voice_chats", log_text, None, chat_id)
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
                    
                    await log_to_thread("voice_chats", log_text, None, chat_id)
                    
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
                            
                            await log_to_thread("voice_chats", log_text, None, chat_id)
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
                            
                            await log_to_thread("voice_chats", log_text, None, chat_id)
                        except Exception as e:
                            logger.error(f"Sesli sohbetten ayrılma loglanırken hata oluştu: {e}")
    except Exception as e:
        logger.error(f"Sesli sohbet event işleyicisinde hata: {e}")

# MODERASYON KOMUTLARI
# Anti-flood functionality

# Dictionary to track user messages: {chat_id: {user_id: [message_timestamps]}}
user_messages = {}

# Ban komutu
# Ban komutu
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
        
        # Admin'in ban sayısını güncelle ve al
        ban_count = update_admin_action_count(chat.id, event.sender_id, "ban")
        
        # İtiraz butonu oluştur (daha önce değiştirdiğiniz gibi URL olarak)
        appeal_button = Button.url("Bana İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Ban'i logla
        log_text = f"🚫 **KULLANICI BANLANDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {banned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Yöneticinin Ban Sayısı:** {ban_count}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Log kanalına log mesajı gönder (buttonsız)
        await log_to_thread("ban", log_text, None, chat.id)
        
        # Ban işlemi yapıldıktan sonra kullanıcıyı banned_users listesine ekle
        if "banned_users" not in config:
            config["banned_users"] = {}
        if str(chat.id) not in config["banned_users"]:
            config["banned_users"][str(chat.id)] = {}

        config["banned_users"][str(chat.id)][str(user_id)] = {
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "reason": reason,
            "admin_id": event.sender_id,
            "user_name": banned_user.first_name
        }
        save_config(config)
        
        # Gruba ban mesajı ve itiraz butonu gönder
        await event.respond(
            f"Kullanıcı {banned_user.first_name} şu sebepten banlandı: {reason}", 
            buttons=[[appeal_button]]
        )
    except UserAdminInvalidError:
        await event.respond("Bir yöneticiyi banlayamam.")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Unban komutu
# Unban komutu
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
        
        # Kullanıcıyı banned_users listesinden çıkar
        if "banned_users" in config and str(chat.id) in config["banned_users"] and str(user_id) in config["banned_users"][str(chat.id)]:
            del config["banned_users"][str(chat.id)][str(user_id)]
            save_config(config)
        
        await event.respond(f"Kullanıcı {unbanned_user.first_name} ban kaldırıldı. Sebep: {reason}")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Mute komutu
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
        until_date = datetime.now() + timedelta(days=999)
        
    
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
        
        # Admin'in mute sayısını güncelle ve al
        mute_count = update_admin_action_count(chat.id, event.sender_id, "mute")
        
        # İtiraz butonu oluştur (URL olarak)
        appeal_button = Button.url("Susturmaya İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Mute'u logla
        until_text = "süresiz" if not until_date else f"{until_date.strftime('%Y-%m-%d %H:%M:%S')} tarihine kadar"
        log_text = f"🔇 **KULLANICI SUSTURULDU**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {muted_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Yöneticinin Mute Sayısı:** {mute_count}\n" \
                  f"**Süre:** {duration_text}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Log kanalına log mesajı gönder (buttonsız)
        await log_to_thread("mute", log_text, None, chat.id)
        
        # Mute işlemi yapıldıktan sonra kullanıcıyı muted_users listesine ekle
        if "muted_users" not in config:
            config["muted_users"] = {}
        if str(chat.id) not in config["muted_users"]:
            config["muted_users"][str(chat.id)] = {}

        config["muted_users"][str(chat.id)][str(user_id)] = {
            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "reason": reason,
            "admin_id": event.sender_id,
            "user_name": muted_user.first_name,
            "until_date": until_date.strftime('%Y-%m-%d %H:%M:%S') if until_date else "Süresiz"
        }
        save_config(config)
        
        # Gruba mute mesajı ve itiraz butonu gönder
        await event.respond(
            f"Kullanıcı {muted_user.first_name} {duration_text} boyunca şu sebepten susturuldu: {reason}",
            buttons=[[appeal_button]]
        )
    except UserAdminInvalidError:
        await event.respond("Bir yöneticiyi susturamam.")
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Unmute komutu
# Unmute komutu
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
        
        # Kullanıcıyı muted_users listesinden çıkar
        if "muted_users" in config and str(chat.id) in config["muted_users"] and str(user_id) in config["muted_users"][str(chat.id)]:
            del config["muted_users"][str(chat.id)][str(user_id)]
            save_config(config)
        
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
        await event.respond("Lütfen atılma sebebi belirtin.")
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
        
        # Admin'in kick sayısını güncelle ve al
        kick_count = update_admin_action_count(chat.id, event.sender_id, "kick")
        
        # İtiraz butonu oluştur (URL olarak)
        appeal_button = Button.url("Atılmaya İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Kick'i logla
        log_text = f"👢 **KULLANICI ATILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {kicked_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Yöneticinin Kick Sayısı:** {kick_count}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Log kanalına log mesajı gönder (buttonsız)
        await log_to_thread("kick", log_text, None, chat.id)
        
        # Gruba kick mesajı ve itiraz butonu gönder
        await event.respond(
            f"Kullanıcı {kicked_user.first_name} şu sebepten atıldı: {reason}",
            buttons=[[appeal_button]]
        )
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
        
        # İtiraz butonu oluştur
        appeal_button = Button.url("Bana İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Uyarıyı logla
        log_text = f"⚠️ **KULLANICI UYARILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {warned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Log kanalına log mesajı gönder
        await log_to_thread("warns", log_text, None, chat.id)
        
        response = f"Kullanıcı {warned_user.first_name} şu sebepten uyarıldı: {reason}\n" \
                  f"Uyarı Sayısı: {warn_count}/{warn_settings['max_warns']}"
        
        # Gruba uyarı mesajı ve itiraz butonu gönder
        buttons = [[appeal_button]]
        
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
                
                await log_to_thread("ban", log_text, None, chat.id)
                
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
                
                await log_to_thread("mute", log_text, None, chat.id)
            
            # Uyarı sayısını sıfırla
            config["groups"][chat_id_str]["user_warnings"][user_id_str] = []
            save_config(config)
        
        await event.respond(response, buttons=buttons)
        
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Unwarn komutu
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
        
        await log_to_thread("warns", log_text, None, chat.id)
        
        await event.respond(f"Kullanıcı {warned_user.first_name} bir uyarısı kaldırıldı.\n"
                          f"Kalan Uyarı Sayısı: {warn_count}/{warn_settings['max_warns']}\n"
                          f"Sebep: {reason}")
        
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")
        
# Kullanıcının gruba attığı mesaj sayısını sayan fonksiyon
# Kullanıcının gruba attığı mesaj sayısını sayan fonksiyon
async def count_user_messages(chat_id, user_id):
    """
    Belirli bir kullanıcının belirli bir gruptaki toplam mesaj sayısını sayar.
    
    Args:
        chat_id: Grubun ID'si
        user_id: Kullanıcının ID'si
        
    Returns:
        int/str: Kullanıcının toplam mesaj sayısı
    """
    try:
        # Telethon API kullanarak mesaj sayısını al
        count = 0
        # Güncel tarih ve sınır belirle (son 30 gün gibi)
        today = datetime.now()
        limit_date = today - timedelta(days=30)  # Son 30 gündeki mesajları say
        
        # Mesajları sorgula ve say
        async for message in client.iter_messages(
            entity=chat_id,
            from_user=user_id,
            offset_date=limit_date,
            reverse=True
        ):
            count += 1
            # 100'den fazla mesajı saymayı durdur (performans için)
            if count >= 100:
                count = str(count) + "+"
                break
                
        return count
    except Exception as e:
        logger.error(f"Mesaj sayımı sırasında hata: {e}")
        return "Hesaplanamadı"

# Kullanıcı bilgisi komutu
# Kullanıcı bilgisi komutu - geliştirilmiş versiyon
# Düzeltilmiş tam çalışan kullanıcı bilgisi komutu
# Düzeltilmiş tam çalışan kullanıcı bilgisi komutu
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
    chat_id = chat.id  # Chat ID'yi tanımla
    chat_id_str = ensure_group_in_config(chat_id)
    
    try:
        user = await client.get_entity(user_id)
        
        # Kullanıcının gruba katılma tarihini al
        join_date = "Bilinmiyor"
        try:
            participant = await client(GetParticipantRequest(chat, user_id))
            join_date = participant.participant.date.strftime('%Y-%m-%d %H:%M:%S')
            
            # Kullanıcının yetkilerini kontrol et
            user_status = "Üye"
            if isinstance(participant.participant, ChannelParticipantAdmin):
                user_status = "Yönetici"
            elif isinstance(participant.participant, ChannelParticipantCreator):
                user_status = "Grup Kurucusu"
        except Exception as e:
            logger.error(f"Katılım tarihi alınırken hata: {e}")
            join_date = "Bilinmiyor"
            user_status = "Bilinmiyor/Grupta Değil"
        
        # Kullanıcının uyarı sayısını al
        warn_count = 0
        if "user_warnings" in config["groups"][chat_id_str]:
            if str(user_id) in config["groups"][chat_id_str]["user_warnings"]:
                warn_count = len(config["groups"][chat_id_str]["user_warnings"][str(user_id)])
        
        # Kullanıcının mevcut cezaları kontrol edilir
        current_restrictions = "Yok"
        try:
            # Kullanıcı katılımcı bilgilerini al
            participant = await client(GetParticipantRequest(chat, user_id))
            
            # Eğer kısıtlama varsa
            if hasattr(participant.participant, 'banned_rights'):
                banned_rights = participant.participant.banned_rights
                
                if banned_rights.view_messages:
                    current_restrictions = "⛔️ Banlanmış"
                elif banned_rights.send_messages:
                    if banned_rights.until_date and banned_rights.until_date > datetime.now():
                        # Kalan süreyi hesapla
                        remaining_time = banned_rights.until_date - datetime.now()
                        hours, remainder = divmod(remaining_time.total_seconds(), 3600)
                        minutes, _ = divmod(remainder, 60)
                        current_restrictions = f"🔇 Susturulmuş ({int(hours)} saat, {int(minutes)} dakika kaldı)"
                    else:
                        current_restrictions = "🔇 Susturulmuş"
        except Exception as e:
            logger.debug(f"Kısıtlama kontrolünde hata: {e}")
            
        # Kullanıcı bilgisini hazırla
        user_info = f"👤 **KULLANICI BİLGİSİ**\n\n"
        user_info += f"**İsim:** {user.first_name}"
        
        if user.last_name:
            user_info += f" {user.last_name}"
        
        user_info += "\n"
        
        if user.username:
            user_info += f"**Kullanıcı Adı:** @{user.username}\n"
        
        # Kalan bilgileri ekle
        user_info += f"**ID:** `{user_id}`\n"
        user_info += f"**Durum:** {user_status}\n"
        user_info += f"**Gruba Katılma:** {join_date}\n"
        
        # Mesaj sayımı gerçekleştirelim
        message_count = await count_user_messages(chat_id, user_id)
        
        user_info += f"**Uyarı Sayısı:** {warn_count}\n"
        user_info += f"**Mevcut Cezalar:** {current_restrictions}\n\n"
        user_info += f"**Yönetim İşlemleri:**"
        
        # Yönetim butonlarını adminler için hazırla
        buttons = []
        if await check_admin_permission(event, "ban"):
            ban_button = Button.inline("🚫 Ban", data=f"direct_action_ban_{user_id}")
            unban_button = Button.inline("✅ Unban", data=f"direct_action_unban_{user_id}")
            buttons.append([ban_button, unban_button])
            
        if await check_admin_permission(event, "mute"):
            mute_button = Button.inline("🔇 Mute", data=f"direct_action_mute_{user_id}")
            unmute_button = Button.inline("🔊 Unmute", data=f"direct_action_unmute_{user_id}")
            buttons.append([mute_button, unmute_button])
            
        if await check_admin_permission(event, "kick"):
            kick_button = Button.inline("👢 Kick", data=f"direct_action_kick_{user_id}")
            buttons.append([kick_button])
            
        if await check_admin_permission(event, "warn"):
            warn_button = Button.inline("⚠️ Warn", data=f"direct_action_warn_{user_id}")
            unwarn_button = Button.inline("🔄 Unwarn", data=f"direct_action_unwarn_{user_id}")
            buttons.append([warn_button, unwarn_button])
        
        # Eğer hiçbir yetki yoksa, boş mesaj göster
        if not buttons:
            user_info += "\n⚠️ Yönetim işlemleri için yetkiniz yok."
            await event.respond(user_info)
        else:
            await event.respond(user_info, buttons=buttons)
    except Exception as e:
        await event.respond(f"Kullanıcı bilgisi alınırken hata oluştu: {str(e)}")
        
        
# Direkt işlem butonları için handler
@client.on(events.CallbackQuery(pattern=r'direct_action_(ban|unban|mute|unmute|kick|warn|unwarn)_(\d+)'))
async def direct_action_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        
        # İlgili yetki kontrolü
        if action in ["ban", "unban"]:
            permission_type = "ban"
        elif action in ["mute", "unmute"]:
            permission_type = "mute"
        elif action == "kick":
            permission_type = "kick"
        elif action in ["warn", "unwarn"]:
            permission_type = "warn"
        else:
            permission_type = action
            
        # Yetki kontrolü
        if not await check_admin_permission(event, permission_type):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # İşlem onayını göster
        await event.answer(f"{action.capitalize()} işlemi gerçekleştiriliyor...")
        
        # Gruptan bilgileri al
        chat = await event.get_chat()
        chat_id = chat.id
        
        # İşlemi yapacak kullanıcı bilgileri
        admin = await event.get_sender()
        
        # Hedef kullanıcı bilgileri
        try:
            target_user = await client.get_entity(user_id)
            target_name = f"{target_user.first_name} {target_user.last_name if target_user.last_name else ''}"
        except:
            target_name = f"ID: {user_id}"
        
        # Standart sebep metni
        reason = f"Yönetici tarafından {action} butonuyla"
        
        # İşleme göre işlem yap
        if action == "ban":
            try:
                await client(EditBannedRequest(
                    chat_id,
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
                
                # Ban işlemini logla
                log_text = f"🚫 **KULLANICI BANLANDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("ban", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} başarıyla banlandı"
                
            except Exception as e:
                notification = f"❌ Ban işlemi sırasında hata: {str(e)}"
        
        elif action == "unban":
            try:
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
                
                # Unban işlemini logla
                log_text = f"✅ **KULLANICI BANI KALDIRILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("ban", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} banı kaldırıldı"
                
            except Exception as e:
                notification = f"❌ Ban kaldırma işlemi sırasında hata: {str(e)}"
                
        elif action == "mute":
            try:
                # Varsayılan: 1 saat mute
                until_date = datetime.now() + timedelta(hours=1)
                
                await client(EditBannedRequest(
                    chat_id,
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
                
                # Mute işlemini logla
                log_text = f"🔇 **KULLANICI SUSTURULDU**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Süre:** 1 saat\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("mute", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} 1 saat susturuldu"
                
            except Exception as e:
                notification = f"❌ Mute işlemi sırasında hata: {str(e)}"
                
        elif action == "unmute":
            try:
                await client(EditBannedRequest(
                    chat_id,
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
                
                # Unmute işlemini logla
                log_text = f"🔊 **KULLANICI SUSTURMASI KALDIRILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("mute", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} susturması kaldırıldı"
                
            except Exception as e:
                notification = f"❌ Unmute işlemi sırasında hata: {str(e)}"
                
        elif action == "kick":
            try:
                # Kullanıcıyı at ve sonra yasağı kaldır
                await client(EditBannedRequest(
                    chat_id,
                    user_id,
                    ChatBannedRights(
                        until_date=None,
                        view_messages=True
                    )
                ))
                
                await client(EditBannedRequest(
                    chat_id,
                    user_id,
                    ChatBannedRights(
                        until_date=None,
                        view_messages=False
                    )
                ))
                
                # Kick işlemini logla
                log_text = f"👢 **KULLANICI ATILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("kicks", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} gruptan atıldı"
                
            except Exception as e:
                notification = f"❌ Kick işlemi sırasında hata: {str(e)}"
                
        elif action == "warn":
            try:
                # İşlem için chat_id_str tanımlanmalı
                chat_id_str = str(chat_id)
                
                # Eğer grubun uyarı ayarı yoksa, varsayılan uyarı ayarı kullan
                if "user_warnings" not in config["groups"][chat_id_str]:
                    config["groups"][chat_id_str]["user_warnings"] = {}
                
                # Eğer kullanıcının uyarı kaydı yoksa oluştur
                user_id_str = str(user_id)
                if user_id_str not in config["groups"][chat_id_str]["user_warnings"]:
                    config["groups"][chat_id_str]["user_warnings"][user_id_str] = []
                
                # Yeni uyarı ekle
                warning = {
                    "reason": reason,
                    "admin_id": admin.id,
                    "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                config["groups"][chat_id_str]["user_warnings"][user_id_str].append(warning)
                save_config(config)
                
                # Uyarı sayısını kontrol et
                warn_count = len(config["groups"][chat_id_str]["user_warnings"][user_id_str])
                warn_settings = config["groups"][chat_id_str]["warn_settings"]
                
                # Uyarı işlemini logla
                log_text = f"⚠️ **KULLANICI UYARILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("warns", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} uyarıldı. Uyarı sayısı: {warn_count}/{warn_settings['max_warns']}"
                
                # Maksimum uyarı sayısına ulaşıldıysa ceza uygula
                if warn_count >= warn_settings['max_warns']:
                    if warn_settings['action'] == 'ban':
                        await client(EditBannedRequest(
                            chat_id,
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
                        
                        notification += f"\n⚠️ Kullanıcı maksimum uyarı sayısına ulaştığı için banlandı!"
                        
                        # Ban'i logla
                        log_text = f"🚫 **KULLANICI UYARILAR NEDENİYLE BANLANDI**\n\n" \
                                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                                  f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                                  f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                                  f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        await log_to_thread("ban", log_text, None, chat.id)
                        
                    elif warn_settings['action'] == 'mute':
                        mute_duration = warn_settings.get('mute_duration', 24)  # Saat cinsinden
                        until_date = datetime.now() + timedelta(hours=mute_duration)
                        
                        await client(EditBannedRequest(
                            chat_id,
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
                        
                        notification += f"\n⚠️ Kullanıcı maksimum uyarı sayısına ulaştığı için {mute_duration} saat susturuldu!"
                        
                        # Mute'u logla
                        log_text = f"🔇 **KULLANICI UYARILAR NEDENİYLE SUSTURULDU**\n\n" \
                                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                                  f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                                  f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                                  f"**Süre:** {mute_duration} saat\n" \
                                  f"**Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        await log_to_thread("mute", log_text, None, chat.id)
                    
                    # Uyarı sayısını sıfırla
                    config["groups"][chat_id_str]["user_warnings"][user_id_str] = []
                    save_config(config)
                
            except Exception as e:
                notification = f"❌ Warn işlemi sırasında hata: {str(e)}"
                
        elif action == "unwarn":
            try:
                # İşlem için chat_id_str tanımlanmalı
                chat_id_str = str(chat_id)
                user_id_str = str(user_id)
                
                # Kullanıcının uyarıları var mı kontrol et
                if "user_warnings" not in config["groups"][chat_id_str] or \
                   user_id_str not in config["groups"][chat_id_str]["user_warnings"] or \
                   not config["groups"][chat_id_str]["user_warnings"][user_id_str]:
                    notification = "⚠️ Bu kullanıcının hiç uyarısı yok."
                    await event.edit(notification)
                    return
                
                # Son uyarıyı kaldır
                removed_warning = config["groups"][chat_id_str]["user_warnings"][user_id_str].pop()
                save_config(config)
                
                # Kalan uyarı sayısı
                warn_count = len(config["groups"][chat_id_str]["user_warnings"][user_id_str])
                warn_settings = config["groups"][chat_id_str]["warn_settings"]
                
                # Uyarı kaldırmayı logla
                log_text = f"⚠️ **KULLANICI UYARISI KALDIRILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Kalan Uyarı Sayısı:** {warn_count}/{warn_settings['max_warns']}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("warns", log_text, None, chat.id)
                
                # Bildirim mesajı
                notification = f"✅ Kullanıcı {target_name} bir uyarısı kaldırıldı. Kalan uyarı sayısı: {warn_count}/{warn_settings['max_warns']}"
                
            except Exception as e:
                notification = f"❌ Unwarn işlemi sırasında hata: {str(e)}"
        
        # İşlem sonucunu göster
        await event.edit(notification)
        
        # Kullanıcı bilgilerini güncellenmiş şekilde gösterme
        if not event.is_private:
            # Biraz bekleyip bilgileri yenile
            await asyncio.sleep(1)
            # Yeni info komutu çalıştır
            command_message = await event.get_message()
            if command_message:
                info_command_text = f"/info {user_id}"
                await client.send_message(event.chat_id, info_command_text)
        
    except Exception as e:
        logger.error(f"Direkt işlem butonunda hata: {str(e)}")
        await event.answer(f"İşlem sırasında bir hata oluştu: {str(e)}", alert=True)

# Kullanıcı mesaj istatistiklerini takip etme (track_messages fonksiyonuna güncelleştir)
# Kullanıcı mesaj istatistiklerini takip etme (track_messages fonksiyonuna güncelleştir)
@client.on(events.NewMessage)
async def track_messages(event):
    if not event.is_private and event.message:
        # Mevcut kod, günlük istatistikleri artırmak
        increment_stat("messages", event.chat_id)
        
        # Kullanıcının bu gruptaki toplam mesaj sayısını artırmak için (yeni)
        try:
            chat_id_str = str(event.chat_id)
            user_id_str = str(event.sender_id)
            
            # Grup user_stats alanını kontrol et/oluştur
            if "user_stats" not in config["groups"][chat_id_str]:
                config["groups"][chat_id_str]["user_stats"] = {}
            
            # Kullanıcı alanını kontrol et/oluştur  
            if user_id_str not in config["groups"][chat_id_str]["user_stats"]:
                config["groups"][chat_id_str]["user_stats"][user_id_str] = {"messages": 0, "last_active": 0}
            
            # Mesaj sayısını artır
            config["groups"][chat_id_str]["user_stats"][user_id_str]["messages"] += 1
            # Son aktif zamanı güncelle
            config["groups"][chat_id_str]["user_stats"][user_id_str]["last_active"] = int(time.time())
            
            # Her 10 mesajda bir kaydet (performans optimizasyonu)
            if config["groups"][chat_id_str]["user_stats"][user_id_str]["messages"] % 10 == 0:
                save_config(config)
        except Exception as e:
            logger.error(f"Kullanıcı mesaj istatistiği güncelleme hatası: {e}")
# BUTON İŞLEYİCİLERİ
# Basit günlük istatistik özelliği

# Thread ID for stats in the log channel
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
                await log_to_thread("stats", header + all_reports, None, None)
            
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
# İtiraz işleme butonları (kaldığınız yerden devam)
# İtiraz işleme butonları
# İtiraz işleme butonları - DÜZELTİLMİŞ VERSİYON
# İtiraz işleme butonları - GELİŞMİŞ VERSİYON


# İtiraz değerlendirme butonları
# İtiraz değerlendirme butonları
# İtiraz değerlendirme butonları

# İtiraz değerlendirme butonları - Düzeltilmiş versiyon
# İtiraz değerlendirme butonları - Geliştirilmiş mute kaldırma versiyonu
@client.on(events.CallbackQuery(pattern=r'appeal_(approve|reject)_(ban|mute|kick|warn)_(\d+)'))
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
        
        await event.answer("İşleniyor...")
        
        try:
            # İtiraz eden kullanıcının bilgilerini al
            try:
                appealing_user = await client.get_entity(user_id)
                user_name = f"{appealing_user.first_name} {appealing_user.last_name if appealing_user.last_name else ''}"
            except Exception as e:
                logger.error(f"İtiraz eden kullanıcı bilgisi alınamadı: {e}")
                user_name = f"Kullanıcı (ID: {user_id})"
            
            # Kullanıcının bulunduğu grupları bul
            user_groups = []
            all_groups = []  # Tüm grupları kontrol et, sadece uyarısı olan grupları değil
            
            # İşlem yapmadan önce tüm grupları kontrol et
            for chat_id_str in config["groups"]:
                all_groups.append(int(chat_id_str))
                if "user_warnings" in config["groups"][chat_id_str] and str(user_id) in config["groups"][chat_id_str]["user_warnings"]:
                    user_groups.append(int(chat_id_str))
            
            if decision == "approve":
                # Cezayı kaldır
                success_message = ""
                success_count = 0
                
                # İlk olarak kullanıcının uyarı kayıtlarından bulunan gruplarda işlem yap
                if user_groups:
                    for group_id in user_groups:
                        if action == "ban" or action == "mute":
                            try:
                                # Grup bilgisini al
                                group = await client.get_entity(group_id)
                                
                                # Ban veya mute cezasını kaldır - DÜZGÜN ÇALIŞAN VERSİYON
                                rights = ChatBannedRights(
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
                                
                                await client(EditBannedRequest(
                                    group_id,
                                    user_id,
                                    rights
                                ))
                                
                                success_message += f"{group.title} grubundaki {action} cezası kaldırıldı. "
                                logger.info(f"{user_id} için {group_id} grubunda {action} cezası kaldırıldı")
                                success_count += 1
                            except Exception as e:
                                logger.error(f"{group_id} grubunda {action} cezası kaldırılırken hata: {e}")
                                success_message += f"{group_id} grubunda işlem başarısız: {str(e)}. "
                        
                        # Uyarıları temizle
                        if action == "warn":
                            try:
                                chat_id_str = str(group_id)
                                if "user_warnings" in config["groups"][chat_id_str] and str(user_id) in config["groups"][chat_id_str]["user_warnings"]:
                                    config["groups"][chat_id_str]["user_warnings"][str(user_id)] = []
                                    save_config(config)
                                    success_message += f"{group_id} grubundaki tüm uyarılar silindi. "
                                    logger.info(f"{user_id} için {group_id} grubunda tüm uyarılar silindi")
                                    success_count += 1
                            except Exception as e:
                                logger.error(f"{group_id} grubunda uyarılar silinirken hata: {e}")
                                success_message += f"{group_id} grubunda uyarılar silinirken hata: {str(e)}. "
                else:
                    # Eğer kullanıcının uyarı kaydı yoksa, tüm gruplarda işlem yapmayı dene
                    if action == "ban" or action == "mute":
                        for group_id in all_groups:
                            try:
                                # Grup bilgisini al
                                group = await client.get_entity(group_id)
                                
                                # Ban veya mute cezasını kaldır
                                rights = ChatBannedRights(
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
                                
                                await client(EditBannedRequest(
                                    group_id,
                                    user_id,
                                    rights
                                ))
                                
                                success_message += f"{group.title} grubundaki {action} cezası kaldırıldı. "
                                logger.info(f"{user_id} için {group_id} grubunda {action} cezası kaldırıldı")
                                success_count += 1
                            except Exception as e:
                                # Bu grup için işlem başarısız olabilir, sessizce devam et
                                logger.debug(f"{group_id} grubunda {action} cezası kaldırılırken hata: {e}")
                
                # Eğer hiçbir işlem başarılı olmadıysa ve mute kaldırma işlemiyse, ek bir yöntem deneyelim
                if success_count == 0 and action == "mute":
                    try:
                        # Eğer mesajın geldiği grup bilgisi alınabilirse orada işlem yapalım
                        message_chat = await event.get_chat()
                        if not isinstance(message_chat, types.User):  # Özel mesaj değilse
                            # Grup bilgisini al
                            try:
                                group = await client.get_entity(message_chat.id)
                                
                                # Mute cezasını kaldır - alternatif yöntem
                                rights = ChatBannedRights(
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
                                
                                await client(EditBannedRequest(
                                    message_chat.id,
                                    user_id,
                                    rights
                                ))
                                
                                success_message = f"{group.title} grubundaki {action} cezası kaldırıldı (doğrudan yöntemle). "
                                logger.info(f"{user_id} için {message_chat.id} grubunda {action} cezası kaldırıldı (doğrudan)")
                                success_count = 1
                            except Exception as e:
                                logger.error(f"Doğrudan mute kaldırmada hata: {e}")
                    except Exception as e:
                        logger.error(f"Alternatif mute kaldırma yöntemi başarısız: {e}")
                
                # Başarı durumunu kontrol et
                if success_count == 0:
                    success_message = "Hiçbir grupta ceza kaldırma işlemi başarılı olmadı. Lütfen manuel olarak cezayı kaldırın."
                
                response_text = f"✅ **İTİRAZ ONAYLANDI**\n\n" \
                            f"**Kullanıcı:** {user_name} (`{user_id}`)\n" \
                            f"**Ceza Türü:** {action}\n" \
                            f"**Onaylayan:** {event.sender.first_name}\n" \
                            f"**Sonuç:** {success_message}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                # Kullanıcıya bildirim gönder
                try:
                    await client.send_message(user_id, f"İtirazınız onaylandı ve {action} cezanız kaldırıldı.")
                except Exception as e:
                    logger.error(f"Kullanıcıya onay bildirimi gönderilemedi: {e}")
                    
            else:  # reject
                response_text = f"❌ **İTİRAZ REDDEDİLDİ**\n\n" \
                            f"**Kullanıcı:** {user_name} (`{user_id}`)\n" \
                            f"**Ceza Türü:** {action}\n" \
                            f"**Reddeden:** {event.sender.first_name}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                # Kullanıcıya bildirim gönder
                try:
                    await client.send_message(user_id, f"İtirazınız reddedildi ve {action} cezanız devam edecek.")
                except Exception as e:
                    logger.error(f"Kullanıcıya red bildirimi gönderilemedi: {e}")
            
            # İtiraz mesajını güncelle
            # ÖNEMLİ: Mesajı düzenleme hatası için düzeltme
            try:
                # Önce mesajı almayı deneyelim ve sonra düzenleyelim
                original_message = await event.get_message()
                
                if original_message:
                    # Butonları kaldırarak mesajı düzenle
                    await original_message.edit(
                        text=response_text,
                        buttons=None
                    )
                else:
                    # Mesaj alınamadıysa yeni bir mesaj gönderelim
                    await event.respond(response_text)
                    
            except Exception as e:
                logger.error(f"Mesaj düzenleme hatası: {e}")
                # Alternatif olarak yeni mesaj gönder
                await event.respond(response_text + "\n\n[Orijinal mesaj düzenlenemedi]")
            
        except Exception as e:
            logger.error(f"İtiraz karar işleminde hata: {e}")
            await event.respond(f"İtiraz işlemi sırasında bir hata oluştu: {str(e)}")
    except Exception as e:
        logger.error(f"İtiraz değerlendirme buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)
# YASAKLI KELİME VE BAĞLANTI FİLTRELEME

# Yasaklı kelime ayarları
@client.on(events.NewMessage(pattern=r'/blacklist'))
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
        
# Anti-flood denetlemesi için event handler
@client.on(events.NewMessage)
async def flood_check_handler(event):
    # İki veya daha fazla kelimesi olan mesajları daha az kontrol et
    if len(event.raw_text.split()) > 2:
        # Her mesajı kontrol etmek yerine, rastgele mesaj atla (performans için)
        import random
        if random.random() < 0.7:  # %70 ihtimalle bu mesajı kontrol etme
            return
    
    # Flood kontrolü yap
    await check_flood(event)

# Mesaj filtreleme (yasaklı kelimeler ve bağlantılar)
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
                        
                        await log_to_thread("forbidden_words", log_text, None, chat.id)
                        return
                    except:
                        pass
        
        # Sadece bağlantı kontrolü (mention kontrolü kaldırıldı)
        if not is_admin:
            # Telegram bağlantıları ve web bağlantıları kontrol et
            has_link = False
            link_type = None
            link_value = None
            
            # Metin içinde URL kontrolü
            if re.search(r'(https?://\S+|www\.\S+)', text):
                has_link = True
                link_type = "URL"
                link_value = re.findall(r'(https?://\S+|www\.\S+)', text)
            
            # Telegram t.me/ bağlantıları kontrolü
            elif re.search(r't\.me/[\w\+]+', text):
                has_link = True
                link_type = "Telegram"
                link_value = re.findall(r't\.me/[\w\+]+', text)
            
            # Mesaj varlıklarında URL kontrolü
            elif message.entities:
                for entity in message.entities:
                    if isinstance(entity, (MessageEntityUrl, MessageEntityTextUrl)):
                        has_link = True
                        link_type = "Entity URL"
                        break
            
            # Eğer bir link bulunursa, mesajı sil ve logla
            if has_link:
                try:
                    await event.delete()
                    
                    # Bağlantı paylaşımını logla
                    log_text = f"🔗 **YASAK BAĞLANTI PAYLAŞILDI**\n\n" \
                            f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                            f"**Kullanıcı:** {sender.first_name} (`{sender.id}`)\n" \
                            f"**Bağlantı Türü:** {link_type}\n" \
                            f"**Bağlantı:** {link_value if link_value else 'Entity'}\n" \
                            f"**Mesaj:** {text}\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    await log_to_thread("forbidden_words", log_text, None, chat.id)
                except Exception as e:
                    logger.error(f"Yasaklı içerik silme hatası: {e}")
    except Exception as e:
        logger.error(f"Mesaj filtreleme sırasında hata: {str(e)}")
# HOŞGELDİN MESAJLARI

# Hoşgeldin mesajı ayarları
@client.on(events.NewMessage(pattern=r'/welcome'))
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
        
        await log_to_thread("join_leave", log_text, None, chat.id)
        
        # Hoşgeldin mesajı etkinse gönder
        if "welcome_message" in config["groups"][chat_id_str] and config["groups"][chat_id_str]["welcome_message"]["enabled"]:
            welcome_settings = config["groups"][chat_id_str]["welcome_message"]
            
            welcome_text = welcome_settings["text"].replace("{user}", f"[{user.first_name}](tg://user?id={user.id})").replace("{username}", f"@{user.username}" if user.username else user.first_name)
            
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
        
        await log_to_thread("join_leave", log_text, None, chat.id)
    except Exception as e:
        logger.error(f"Üye ayrılma loglamasında hata: {str(e)}")

# TEKRARLANAN MESAJLAR

# Aralığı metin olarak biçimlendirmek için yardımcı fonksiyon
def format_interval(seconds):
    if seconds < 60:
        return f"{seconds} saniye"
    elif seconds < 3600:
        return f"{seconds // 60} dakika"
    else:
        return f"{seconds // 3600} saat"

# Tekrarlanan mesaj ayarları menüsü
@client.on(events.NewMessage(pattern=r'/amsj'))
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

# Varsayılan ayarlar için buton işleyici
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

# Varsayılan süre için buton işleyici
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

# Tekrarlanan mesajları togle etme
@client.on(events.CallbackQuery(pattern=r'repeated_toggle_(-?\d+)'))
async def repeated_toggle_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        repeated_settings = config["groups"][chat_id_str]["repeated_messages"]
        
        # Durumu değiştir
        repeated_settings["enabled"] = not repeated_settings["enabled"]
        save_config(config)
        
        status = "aktif" if repeated_settings["enabled"] else "devre dışı"
        await event.answer(f"Tekrarlanan mesajlar {status} olarak ayarlandı.")
        
        # Ana menüye dön
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Tekrarlanan mesaj toggle işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Mesaj ekleme işlevi
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
# Butonları temizleme onayı (kaldığı yerden devam)
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

# Tekrarlanan mesajları gönderme işlevi
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
                                
                                await log_to_thread("repeated_msgs", log_text, None, chat_id)
                                
                            except Exception as e:
                                logger.error(f"Tekrarlanan mesaj gönderilirken hata oluştu: {e}")
            
        except Exception as e:
            logger.error(f"Tekrarlanan mesaj döngüsünde hata oluştu: {e}")
        
        # Her 30 saniyede bir kontrol et
        await asyncio.sleep(30)

# YÖNETİCİ YETKİLERİ

# Yetki verme komutu
@client.on(events.NewMessage(pattern=r'/promote(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
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
            
            await log_to_thread("join_leave", log_text, None, chat.id)  # Özel bir log thread'i oluşturulabilir
            
        except Exception as e:
            await event.respond(f"Bir hata oluştu: {str(e)}")
    else:
        await event.respond("Bu kullanıcının zaten bu yetkisi var.")

# Yetki alma komutu
@client.on(events.NewMessage(pattern=r'/demote(?:@\w+)?(\s+(?:@\w+|\d+))?(\s+.+)?'))
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
            
            await log_to_thread("join_leave", log_text, None, chat.id)  # Özel bir log thread'i oluşturulabilir
            
        except Exception as e:
            await event.respond(f"Bir hata oluştu: {str(e)}")
    else:
        await event.respond("Bu kullanıcıda bu yetki zaten yok.")

# UYARI AYARLARI

# Uyarı ayarları
@client.on(events.NewMessage(pattern=r'/wset'))
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
# Admin kontrolü için yardımcı fonksiyon
async def is_admin(chat, user_id):
    try:
        participant = await client(GetParticipantRequest(channel=chat, participant=user_id))
        return isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator))
    except:
        return False

# Anti-flood config ekleme
def add_flood_config_to_group(chat_id):
    """Bir gruba flood koruması yapılandırması ekle"""
    chat_id_str = str(chat_id)
    if chat_id_str not in config["groups"]:
        config["groups"][chat_id_str] = {}
    
    if "flood_settings" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["flood_settings"] = DEFAULT_FLOOD_CONFIG.copy()
        save_config(config)
    
    return config["groups"][chat_id_str]["flood_settings"]

# Anti-flood kontrolü
async def check_flood(event):
    """
    Anti-flood kontrolü yapar, eğer kullanıcı flood yapıyorsa belirlenen eylemi uygular.
    
    :param event: Mesaj olayı
    :return: True (flood algılandı), False (flood algılanmadı)
    """
    if event.is_private:
        return False  # Özel mesajlarda flood kontrolü yapma
    
    # Grup ve kullanıcı ID'leri
    chat_id = event.chat_id
    chat_id_str = str(chat_id)
    user_id = event.sender_id
    
    # Grup flood ayarlarını al, yoksa varsayılan ayarları ekle
    if chat_id_str not in config["groups"] or "flood_settings" not in config["groups"][chat_id_str]:
        flood_settings = add_flood_config_to_group(chat_id)
    else:
        flood_settings = config["groups"][chat_id_str]["flood_settings"]
    
    # Anti-flood devre dışı ise işlem yapma
    if not flood_settings.get("enabled", False):
        return False
    
    # Adminleri hariç tut seçeneği aktif ve kullanıcı admin ise, kontrol etme
    if flood_settings.get("exclude_admins", True) and await is_admin(event.chat, user_id):
        return False
    
    current_time = datetime.now()
    # Son mesajların zamanlarını sakla
    flood_data[chat_id][user_id].append(current_time)
    
    # Belirlenen süreden daha eski mesajları temizle
    time_threshold = current_time - timedelta(seconds=flood_settings.get("seconds", 5))
    flood_data[chat_id][user_id] = [t for t in flood_data[chat_id][user_id] if t > time_threshold]
    
    # Son belirli süre içindeki mesaj sayısını kontrol et
    if len(flood_data[chat_id][user_id]) > flood_settings.get("messages", 5):
        # Flood algılandı, ayarlara göre işlem yap
        action = flood_settings.get("action", "mute")
        
        try:
            # Kullanıcı bilgilerini al
            flooder = await client.get_entity(user_id)
            flooder_name = getattr(flooder, 'first_name', 'Bilinmeyen') + ((' ' + getattr(flooder, 'last_name', '')) if getattr(flooder, 'last_name', '') else '')
            
            # Grup bilgilerini al
            chat = await client.get_entity(chat_id)
            
            # Log metni hazırla
            log_text = f"⚠️ **FLOOD ALGILANDI**\n\n" \
                       f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                       f"**Kullanıcı:** {flooder_name} (`{user_id}`)\n" \
                       f"**Süre içindeki mesaj sayısı:** {len(flood_data[chat_id][user_id])}\n" \
                       f"**Zaman aralığı:** {flood_settings.get('seconds', 5)} saniye\n" \
                       f"**Uygulanan işlem:** {action.upper()}\n" \
                       f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Sadece uyarı seçeneği aktif ve admin değilse, uyarı gönder
            if flood_settings.get("warn_only", False) and not await is_admin(event.chat, user_id):
                await event.respond(f"⚠️ @{flooder.username if hasattr(flooder, 'username') and flooder.username else user_id} Lütfen flood yapmayın!")
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_warn", log_text, None, chat_id)
                
                return True
                
            # Action'a göre işlem yap
            if action.lower() == "mute":
                # Mute işlemi
                mute_time = flood_settings.get("mute_time", 5)  # Dakika cinsinden
                until_date = datetime.now() + timedelta(minutes=mute_time)
                
                await client(EditBannedRequest(
                    chat_id,
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
                
                # İtiraz butonu (önceki değişikliklerdeki gibi)
                appeal_button = Button.url("Susturmaya İtiraz Et", "https://t.me/arayis_itiraz")
                
                # Admin'in mute sayısını güncelle ve al
                mute_count = update_admin_action_count(chat_id, event.sender_id, "mute")
                
                # Gruba flood uyarısı gönder
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı {mute_time} dakika susturuldu.",
                    buttons=[[appeal_button]]
                )
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_mute", log_text, None, chat_id)
                
            elif action.lower() == "kick":
                # Kullanıcıyı kickle
                await client(EditBannedRequest(
                    chat_id,
                    user_id,
                    ChatBannedRights(until_date=None, view_messages=True)
                ))
                await client(EditBannedRequest(
                    chat_id,
                    user_id,
                    ChatBannedRights(until_date=None, view_messages=False)
                ))
                
                # İtiraz butonu
                appeal_button = Button.url("Atılmaya İtiraz Et", "https://t.me/arayis_itiraz")
                
                # Admin'in kick sayısını güncelle ve al
                kick_count = update_admin_action_count(chat_id, event.sender_id, "kick")
                
                # Gruba flood uyarısı gönder
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı gruptan atıldı.",
                    buttons=[[appeal_button]]
                )
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_kick", log_text, None, chat_id)
                
            elif action.lower() == "ban":
                # Kullanıcıyı banla
                await client(EditBannedRequest(
                    chat_id,
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
                
                # İtiraz butonu
                appeal_button = Button.url("Bana İtiraz Et", "https://t.me/arayis_itiraz")
                
                # Admin'in ban sayısını güncelle ve al
                ban_count = update_admin_action_count(chat_id, event.sender_id, "ban")
                
                # Gruba flood uyarısı gönder
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı gruptan banlandı.",
                    buttons=[[appeal_button]]
                )
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_ban", log_text, None, chat_id)
                
            elif action.lower() == "warn":
                # Admin'in warn sayısını güncelle ve al
                warn_count = update_admin_action_count(chat_id, event.sender_id, "warn")
                
                # Kullanıcıyı uyar (mevcut warn sisteminizi kullanın)
                await warn_user(event, user_id, "Flood yapmak")
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_warn_system", log_text, None, chat_id)
                
            elif action.lower() == "delete":
                # Sadece mesajı sil
                await event.delete()
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_delete", log_text, None, chat_id)
                
            return True
                
        except Exception as e:
            logger.error(f"Anti-flood işlemi sırasında hata: {str(e)}")
            return False
    
    return False

# Anti-flood ayarlarını değiştirmek için komut
@client.on(events.NewMessage(pattern=r'/setflood(?:@\w+)?(?:\s+(.+))?'))
async def set_flood_command(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    
    if not args:
        # Yardım mesajı göster
        await event.respond(
            "**Anti-Flood Ayarları**\n\n"
            "Kullanım: `/setflood AYAR DEĞER`\n\n"
            "Mevcut ayarlar:\n"
            "- `status` (on/off): Anti-flood sistemini aç/kapa\n"
            "- `messages` (sayı): Zaman aralığında izin verilen mesaj sayısı\n"
            "- `seconds` (sayı): Mesajların izleneceği zaman aralığı (saniye)\n"
            "- `action` (mute/kick/ban/warn/delete): Flood algılandığında yapılacak eylem\n"
            "- `mute_time` (sayı): Mute edilecekse kaç dakika süreyle\n"
            "- `exclude_admins` (yes/no): Yöneticileri anti-flood'dan muaf tut\n"
            "- `warn_only` (yes/no): Sadece uyarı ver, işlem yapma\n"
            "- `log` (yes/no): Anti-flood olaylarını log kanalına bildir\n\n"
            "Örnek: `/setflood messages 7` - 7 mesaj limitiyle anti-flood ayarla"
        )
        return
    
    # Grup ID'sini al
    chat_id = event.chat_id
    chat_id_str = str(chat_id)
    
    # Argümanları böl: /setflood ayar değer
    parts = args.strip().split()
    if len(parts) < 2:
        await event.respond("Hata: Yeterli argüman sağlanmadı. Kullanım: `/setflood AYAR DEĞER`")
        return
    
    setting = parts[0].lower()
    value = parts[1].lower()
    
    # Flood ayarlarını al veya oluştur
    if chat_id_str not in config["groups"] or "flood_settings" not in config["groups"][chat_id_str]:
        flood_settings = add_flood_config_to_group(chat_id)
    else:
        flood_settings = config["groups"][chat_id_str]["flood_settings"]
    
    response = ""
    
    try:
        if setting == "status":
            if value in ["on", "yes", "true", "1"]:
                flood_settings["enabled"] = True
                response = "✅ Anti-flood sistemi açıldı."
            elif value in ["off", "no", "false", "0"]:
                flood_settings["enabled"] = False
                response = "❌ Anti-flood sistemi kapatıldı."
            else:
                response = "⚠️ Geçersiz değer. 'on' veya 'off' kullanın."
        
        elif setting == "messages":
            try:
                msg_count = int(value)
                if msg_count > 0:
                    flood_settings["messages"] = msg_count
                    response = f"✅ Flood mesaj limiti {msg_count} olarak ayarlandı."
                else:
                    response = "⚠️ Mesaj sayısı pozitif bir sayı olmalıdır."
            except ValueError:
                response = "⚠️ Geçersiz sayısal değer."
        
        elif setting == "seconds":
            try:
                seconds = int(value)
                if seconds > 0:
                    flood_settings["seconds"] = seconds
                    response = f"✅ Flood zaman aralığı {seconds} saniye olarak ayarlandı."
                else:
                    response = "⚠️ Saniye değeri pozitif bir sayı olmalıdır."
            except ValueError:
                response = "⚠️ Geçersiz sayısal değer."
        
        elif setting == "action":
            if value in ["mute", "kick", "ban", "warn", "delete"]:
                flood_settings["action"] = value
                response = f"✅ Flood eylemi {value.upper()} olarak ayarlandı."
            else:
                response = "⚠️ Geçersiz eylem. 'mute', 'kick', 'ban', 'warn' veya 'delete' kullanın."
        
        elif setting == "mute_time":
            try:
                mute_time = int(value)
                if mute_time > 0:
                    flood_settings["mute_time"] = mute_time
                    response = f"✅ Flood mute süresi {mute_time} dakika olarak ayarlandı."
                else:
                    response = "⚠️ Mute süresi pozitif bir sayı olmalıdır."
            except ValueError:
                response = "⚠️ Geçersiz sayısal değer."
        
        elif setting == "exclude_admins":
            if value in ["yes", "true", "1", "on"]:
                flood_settings["exclude_admins"] = True
                response = "✅ Yöneticiler anti-flood kontrolünden muaf tutulacak."
            elif value in ["no", "false", "0", "off"]:
                flood_settings["exclude_admins"] = False
                response = "❌ Yöneticiler anti-flood kontrolüne dahil edilecek."
            else:
                response = "⚠️ Geçersiz değer. 'yes' veya 'no' kullanın."
        
        elif setting == "warn_only":
            if value in ["yes", "true", "1", "on"]:
                flood_settings["warn_only"] = True
                response = "✅ Flood durumunda sadece uyarı verilecek."
            elif value in ["no", "false", "0", "off"]:
                flood_settings["warn_only"] = False
                response = "❌ Flood durumunda belirlenen eylem uygulanacak."
            else:
                response = "⚠️ Geçersiz değer. 'yes' veya 'no' kullanın."
        
        elif setting == "log":
            if value in ["yes", "true", "1", "on"]:
                flood_settings["log_to_channel"] = True
                response = "✅ Flood olayları log kanalına bildirilecek."
            elif value in ["no", "false", "0", "off"]:
                flood_settings["log_to_channel"] = False
                response = "❌ Flood olayları log kanalına bildirilmeyecek."
            else:
                response = "⚠️ Geçersiz değer. 'yes' veya 'no' kullanın."
        
        else:
            response = f"⚠️ Bilinmeyen ayar: '{setting}'"
        
        # Değişiklikleri kaydet
        config["groups"][chat_id_str]["flood_settings"] = flood_settings
        save_config(config)
        
        # Mevcut ayarları göster
        current_settings = f"**Mevcut Anti-Flood Ayarları:**\n" \
                          f"- Status: {'ON' if flood_settings.get('enabled', False) else 'OFF'}\n" \
                          f"- Messages: {flood_settings.get('messages', 5)}\n" \
                          f"- Seconds: {flood_settings.get('seconds', 5)}\n" \
                          f"- Action: {flood_settings.get('action', 'mute').upper()}\n" \
                          f"- Mute Time: {flood_settings.get('mute_time', 5)} dakika\n" \
                          f"- Exclude Admins: {'YES' if flood_settings.get('exclude_admins', True) else 'NO'}\n" \
                          f"- Warn Only: {'YES' if flood_settings.get('warn_only', False) else 'NO'}\n" \
                          f"- Log to Channel: {'YES' if flood_settings.get('log_to_channel', True) else 'NO'}"
        
        await event.respond(f"{response}\n\n{current_settings}")
        
    except Exception as e:
        await event.respond(f"⚠️ Ayar değiştirilirken bir hata oluştu: {str(e)}")
        logger.error(f"Anti-flood ayarları değiştirilirken hata: {str(e)}")
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
/blacklist - Yasaklı kelimeler menüsünü açar
/welcome - Hoşgeldin mesajı ayarları
/amsj - Tekrarlanan mesaj ayarları
/wset - Uyarı sistemi ayarları
/log - Log kanalı ve thread ayarları
/setflood - Anti-flood ayarları
/setmember - Toplu üye işlemleri

**👮‍♂️ Yönetici Komutları:**
/promote <kullanıcı> <yetki> - Kullanıcıya özel yetki verir
/demote <kullanıcı> <yetki> - Kullanıcıdan yetkiyi alır

**ℹ️ Diğer Komutlar:**
/yardim - Bu mesajı gösterir
/stat - Grup istatistiklerini gösterir

📢 Tüm moderasyon işlemleri otomatik olarak loglanır.
⚠️ Moderasyon komutları için sebep belirtmek zorunludur.
"""
    
    await event.respond(help_text)


# Log ayarları komutu
# İtiraz işleme butonları - DÜZELTİLMİŞ VERSİYON

# Log ayarları komutu
@client.on(events.NewMessage(pattern=r'/log'))
async def log_settings_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id_str = ensure_group_in_config(chat.id)
    
    # Eğer log ayarları yoksa oluştur
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
    log_channel = log_settings.get("log_channel_id", 0)
    
    # Menü butonları
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if log_settings['enabled'] else 'Aç 🟢'}", 
        data=f"logs_toggle_{chat.id}"
    )
    set_channel_button = Button.inline("📢 Log Kanalı Ayarla", data=f"logs_set_channel_{chat.id}")
    set_threads_button = Button.inline("🧵 Thread ID'leri Ayarla", data=f"logs_set_threads_{chat.id}")
    test_button = Button.inline("🔍 Test Et", data=f"logs_test_{chat.id}")
    
    buttons = [
        [toggle_button],
        [set_channel_button],
        [set_threads_button],
        [test_button]
    ]
    
    log_channel_text = f"ID: {log_channel}" if log_channel else "Ayarlanmamış"
    
    menu_text = f"📝 **Log Ayarları**\n\n" \
                f"**Durum:** {status}\n" \
                f"**Log Kanalı:** {log_channel_text}\n\n" \
                f"Her grup için ayrı log ayarları yaparak, moderasyon işlemlerinin kaydını tutabilirsiniz."
    
    await event.respond(menu_text, buttons=buttons)

# Log ayarları toggle butonu
@client.on(events.CallbackQuery(pattern=r'logs_toggle_(-?\d+)'))
async def logs_toggle_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        log_settings = config["groups"][chat_id_str]["log_settings"]
        
        # Log kanalı ayarlanmış mı kontrol et
        if not log_settings.get("log_channel_id", 0) and not log_settings["enabled"]:
            await event.answer("Önce bir log kanalı ayarlamalısınız!", alert=True)
            return
            
        # Durumu değiştir
        log_settings["enabled"] = not log_settings["enabled"]
        save_config(config)
        
        status = "aktif" if log_settings["enabled"] else "devre dışı"
        await event.answer(f"Log sistemi {status} olarak ayarlandı.")
        
        # Menüyü güncelle
        await log_settings_menu(event)
    
    except Exception as e:
        logger.error(f"Log toggle işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Log kanalı ayarlama
@client.on(events.CallbackQuery(pattern=r'logs_set_channel_(-?\d+)'))
async def logs_set_channel_handler(event):
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
                "Log kanalı ID'sini girin:\n\n"
                "1. Bot'u log kanalına ekleyin ve admin yapın\n"
                "2. Log kanalında bir mesaj gönderin\n"
                "3. Mesajı bu bot'a forward edin\n"
                "4. Ya da doğrudan kanal ID'sini girin (örn. -1001234567890)"
            )
            
            response = await conv.get_response()
            
            # Mesaj forward edilmiş mi kontrol et
            if response.forward:
                try:
                    channel_id = response.forward.chat_id
                except:
                    channel_id = 0
            else:
                # Doğrudan ID girilmiş olabilir
                try:
                    channel_id = int(response.text.strip())
                except:
                    channel_id = 0
            
            if not channel_id:
                await conv.send_message("Geçersiz kanal ID'si. İşlem iptal edildi.")
                return
            
            # Kanalın geçerli olup olmadığını kontrol et
            try:
                channel_entity = await client.get_entity(channel_id)
                # Bot'un bu kanalda admin olup olmadığını kontrol et
                chat = await client.get_entity(channel_id)
                # Chat tipini kontrol et
                if not hasattr(chat, 'megagroup') and not hasattr(chat, 'broadcast'):
                    await conv.send_message("Bu bir kanal veya süper grup değil. İşlem iptal edildi.")
                    return
                    
                # Başarılı olduğunda ayarları güncelle
                config["groups"][chat_id_str]["log_settings"]["log_channel_id"] = channel_id
                save_config(config)
                
                await conv.send_message(f"Log kanalı başarıyla ayarlandı. Kanal ID: {channel_id}")
            except Exception as e:
                await conv.send_message(f"Kanal doğrulanamadı. Hata: {str(e)}")
                return
                
            # Kanalda thread'leri otomatik oluştur
            try:
                # Var olan thread'leri sorgula
                thread_types = ["ban", "mute", "forbidden_words", "join_leave", "kicks", "warns", "voice_chats", "repeated_msgs", "appeals", "stats"]
                thread_titles = {
                    "ban": "🚫 Ban İşlemleri",
                    "mute": "🔇 Susturma İşlemleri",
                    "forbidden_words": "🔤 Yasaklı Kelimeler",
                    "join_leave": "👋 Grup Giriş/Çıkış",
                    "kicks": "👢 Atma İşlemleri",
                    "warns": "⚠️ Uyarı İşlemleri",
                    "voice_chats": "🎙️ Sesli Sohbet",
                    "repeated_msgs": "🔄 Tekrarlanan Mesajlar",
                    "appeals": "🔍 İtirazlar",
                    "stats": "📊 İstatistikler"
                }
                
                created_threads = 0
                thread_message = "Log thread'leri oluşturuluyor...\n"
                
                for thread_type in thread_types:
                    try:
                        # Thread başlığı gönder ve ID'yi kaydet
                        message = await client.send_message(
                            channel_id,
                            f"=== {thread_titles[thread_type]} === #log_{thread_type}"
                        )
                        config["groups"][chat_id_str]["log_settings"]["thread_ids"][thread_type] = message.id
                        created_threads += 1
                        thread_message += f"✅ {thread_titles[thread_type]} thread oluşturuldu\n"
                        await asyncio.sleep(1)  # Flood korumasından kaçınmak için kısa bekle
                    except Exception as e:
                        thread_message += f"❌ {thread_titles[thread_type]} thread oluşturulamadı: {str(e)}\n"
                
                save_config(config)
                
                if created_threads > 0:
                    await conv.send_message(f"{thread_message}\nToplam {created_threads}/10 thread başarıyla oluşturuldu.")
                else:
                    await conv.send_message("Thread'ler oluşturulamadı. Manuel olarak ayarlamak için 'Thread ID'leri Ayarla' seçeneğini kullanın.")
            
            except Exception as e:
                await conv.send_message(f"Thread'ler oluşturulurken bir hata oluştu: {str(e)}")
            
            # Ana menüye dön
            msg = await conv.send_message("Log ayarları menüsüne dönülüyor...")
            await log_settings_menu(await client.get_messages(conv.chat_id, ids=msg.id))
    
    except Exception as e:
        logger.error(f"Log kanalı ayarlama işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Thread ID'lerini ayarlama menüsü
@client.on(events.CallbackQuery(pattern=r'logs_set_threads_(-?\d+)'))
async def logs_set_threads_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        log_settings = config["groups"][chat_id_str]["log_settings"]
        
        # Log kanalı ayarlanmış mı kontrol et
        if not log_settings.get("log_channel_id", 0):
            await event.answer("Önce bir log kanalı ayarlamalısınız!", alert=True)
            return
        
        await event.answer()
        
        # Thread türleri ve butonları
        thread_types = [
            ("ban", "🚫 Ban İşlemleri"), 
            ("mute", "🔇 Susturma İşlemleri"),
            ("forbidden_words", "🔤 Yasaklı Kelimeler"),
            ("join_leave", "👋 Grup Giriş/Çıkış"),
            ("kicks", "👢 Atma İşlemleri"),
            ("warns", "⚠️ Uyarı İşlemleri"),
            ("voice_chats", "🎙️ Sesli Sohbet"),
            ("repeated_msgs", "🔄 Tekrarlanan Mesajlar"),
            ("appeals", "🔍 İtirazlar"),
            ("stats", "📊 İstatistikler")
        ]
        
        buttons = []
        for type_key, type_name in thread_types:
            current_id = log_settings["thread_ids"].get(type_key, 0)
            status = f"{current_id}" if current_id else "Ayarlanmamış"
            buttons.append([Button.inline(f"{type_name} ({status})", data=f"logs_set_thread_{chat_id}_{type_key}")])
        
        # Geri dönüş butonu
        back_button = Button.inline("⬅️ Geri", data=f"logs_back_to_main_{chat_id}")
        buttons.append([back_button])
        
        await event.edit(
            "🧵 **Thread ID Ayarları**\n\n"
            "Ayarlamak istediğiniz log thread'ini seçin.\n"
            "Thread ID'leri, log kanalında ilgili türe ait mesajların gönderileceği başlıklardır.\n\n"
            "Örnek: Bir moderatör kullanıcıyı yasakladığında, log mesajı 'Ban İşlemleri' thread'ine gönderilir.",
            buttons=buttons
        )
    
    except Exception as e:
        logger.error(f"Thread ID'leri menüsü işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Belirli bir thread ID'sini ayarlama
@client.on(events.CallbackQuery(pattern=r'logs_set_thread_(-?\d+)_(\w+)'))
async def logs_set_specific_thread_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        thread_type = event.pattern_match.group(2).decode()
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        log_settings = config["groups"][chat_id_str]["log_settings"]
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            thread_names = {
                "ban": "🚫 Ban İşlemleri",
                "mute": "🔇 Susturma İşlemleri",
                "forbidden_words": "🔤 Yasaklı Kelimeler",
                "join_leave": "👋 Grup Giriş/Çıkış",
                "kicks": "👢 Atma İşlemleri",
                "warns": "⚠️ Uyarı İşlemleri",
                "voice_chats": "🎙️ Sesli Sohbet",
                "repeated_msgs": "🔄 Tekrarlanan Mesajlar",
                "appeals": "🔍 İtirazlar",
                "stats": "📊 İstatistikler"
            }
            
            thread_name = thread_names.get(thread_type, thread_type)
            
            await conv.send_message(
                f"**{thread_name}** için thread ID'sini girin:\n\n"
                "1. Log kanalında ilgili thread başlığı gönderip mesaj ID'sini kopyalayın\n"
                "2. Ya da log kanalındaki bir mesajın ID'sini doğrudan girin\n\n"
                "İptal etmek için 'iptal' yazın."
            )
            
            response = await conv.get_response()
            
            if response.text.lower() == 'iptal':
                await conv.send_message("İşlem iptal edildi.")
                return
            
            try:
                thread_id = int(response.text.strip())
                
                # Thread ID'sini kaydet
                config["groups"][chat_id_str]["log_settings"]["thread_ids"][thread_type] = thread_id
                save_config(config)
                
                await conv.send_message(f"**{thread_name}** için thread ID başarıyla {thread_id} olarak ayarlandı.")
                
            except ValueError:
                await conv.send_message("Geçersiz ID formatı. İşlem iptal edildi.")
            
            # Thread ayarları menüsüne dön
            msg = await conv.send_message("Thread ayarları menüsüne dönülüyor...")
            fake_event = await client.get_messages(conv.chat_id, ids=msg.id)
            fake_event.pattern_match = re.match(r'logs_set_threads_(-?\d+)', f"logs_set_threads_{chat_id}")
            await logs_set_threads_handler(fake_event)
    
    except Exception as e:
        logger.error(f"Thread ID ayarlama işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Log ayarları ana menüsüne dönüş
@client.on(events.CallbackQuery(pattern=r'logs_back_to_main_(-?\d+)'))
async def logs_back_to_main_handler(event):
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

# Log sistemi test fonksiyonu
@client.on(events.CallbackQuery(pattern=r'logs_test_(-?\d+)'))
async def logs_test_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        chat_id_str = ensure_group_in_config(chat_id)
        log_settings = config["groups"][chat_id_str]["log_settings"]
        
        # Log sistemi aktif mi ve kanal ID ayarlanmış mı kontrol et
        if not log_settings.get("enabled", False) or not log_settings.get("log_channel_id", 0):
            await event.answer("Log sistemi aktif değil veya log kanalı ayarlanmamış!", alert=True)
            return
        
        await event.answer("Log sistemi test ediliyor...")
        
        try:
            chat = await event.get_chat()
            thread_types = ["ban", "mute", "forbidden_words", "join_leave", "kicks", "warns", "voice_chats", "repeated_msgs", "appeals", "stats"]
            thread_names = {
                "ban": "🚫 Ban İşlemleri",
                "mute": "🔇 Susturma İşlemleri",
                "forbidden_words": "🔤 Yasaklı Kelimeler",
                "join_leave": "👋 Grup Giriş/Çıkış",
                "kicks": "👢 Atma İşlemleri",
                "warns": "⚠️ Uyarı İşlemleri",
                "voice_chats": "🎙️ Sesli Sohbet",
                "repeated_msgs": "🔄 Tekrarlanan Mesajlar",
                "appeals": "🔍 İtirazlar",
                "stats": "📊 İstatistikler"
            }
            
            success_count = 0
            result_message = "📝 **LOG SİSTEMİ TEST SONUÇLARI**\n\n"
            
            for thread_type in thread_types:
                thread_id = log_settings["thread_ids"].get(thread_type, 0)
                thread_name = thread_names.get(thread_type, thread_type)
                
                if thread_id:
                    try:
                        # Test mesajı gönder
                        test_text = f"🧪 **TEST MESAJI**\n\n" \
                                    f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                                    f"**Log Türü:** {thread_name}\n" \
                                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        message = await client.send_message(
                            log_settings["log_channel_id"],
                            test_text,
                            reply_to=thread_id
                        )
                        
                        success_count += 1
                        result_message += f"✅ {thread_name} - BAŞARILI\n"
                        
                    except Exception as e:
                        result_message += f"❌ {thread_name} - BAŞARISIZ: {str(e)}\n"
                else:
                    result_message += f"⚠️ {thread_name} - ATLANILDI: Thread ID ayarlanmamış\n"
            
            result_message += f"\nToplamda {success_count}/{len(thread_types)} tür için test başarılı oldu."
            
            # Sonucu kullanıcıya bildir
            await event.edit(result_message)
        
        except Exception as e:
            await event.edit(f"Test sırasında bir hata oluştu: {str(e)}")
    
    except Exception as e:
        logger.error(f"Log test işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# İTİRAZ SİSTEMİ İÇİN TEK VE DÜZGÜN FONKSİYON
# UYARI: 1341-1418 ve 1098-3244 satırlarında iki ayrı eski appeal_button_handler fonksiyonu var
# Bunlardan birini kaldırıp diğerini bu yeni fonksiyonla değiştirin:
# Toplu üye işlemleri menüsü
# Toplu üye işlemleri menüsü

        
@client.on(events.CallbackQuery(pattern=r'appeal_(ban|mute|kick|warn)_(\d+)'))
async def appeal_button_handler(event):
    try:
        # Byte tipindeki match gruplarını stringe dönüştür
        action = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        
        # Kullanıcıya bilgi ver
        await event.answer()
        
        try:
            # Mesajı al ve butonları tamamen değiştir
            original_message = await event.get_message()
            
            # Ban/Mute/Kick/Warn itiraz butonunu yeni bir URL butonu ile değiştir
            new_text = original_message.text + "\n\n⚠️ İtiraz sistemi: @arayis_itiraz"
            
            # Sadece URL butonu olan yeni bir buton dizisi oluştur
            new_buttons = [Button.url("🔍 @arayis_itiraz", "https://t.me/arayis_itiraz")]
            
            # Mesajı ve butonları güncelle
            await original_message.edit(
                text=new_text,
                buttons=new_buttons
            )
        except Exception as e:
            logger.error(f"Mesaj düzenleme hatası: {e}")
        
        # Eğer DM varsa, DM üzerinden de buton gönder
        try:
            # Kullanıcıya DM üzerinden buton göndermeyi dene
            await client.send_message(
                user_id,
                f"İtiraz için doğrudan @arayis_itiraz ile iletişime geçebilirsiniz:",
                buttons=[Button.url("@arayis_itiraz", "https://t.me/arayis_itiraz")]
            )
        except Exception as e:
            logger.error(f"DM üzerinden buton gönderilirken hata: {e}")
            pass  # DM yoksa veya hata olursa bu adımı atla
            
    except Exception as e:
        logger.error(f"İtiraz buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)
        
# Admin işlem sayısını takip etme ve güncelleme fonksiyonu
def update_admin_action_count(chat_id, admin_id, action_type):
    """
    Admin işlem sayısını günceller ve yeni sayıyı döndürür
    
    :param chat_id: İşlemin gerçekleştiği grup ID'si
    :param admin_id: İşlemi yapan admin ID'si
    :param action_type: İşlemin türü ('ban', 'mute', 'kick' vb.)
    :return: Güncellenmiş işlem sayısı
    """
    chat_id_str = str(chat_id)
    admin_id_str = str(admin_id)
    
    # Admin_actions anahtarı yoksa oluştur
    if "admin_actions" not in config:
        config["admin_actions"] = {}
    
    # Grup yoksa oluştur
    if chat_id_str not in config["admin_actions"]:
        config["admin_actions"][chat_id_str] = {}
    
    # Admin yoksa oluştur
    if admin_id_str not in config["admin_actions"][chat_id_str]:
        config["admin_actions"][chat_id_str][admin_id_str] = {}
    
    # İşlem türü yoksa oluştur
    if action_type not in config["admin_actions"][chat_id_str][admin_id_str]:
        config["admin_actions"][chat_id_str][admin_id_str][action_type] = 0
    
    # İşlem sayısını 1 artır
    config["admin_actions"][chat_id_str][admin_id_str][action_type] += 1
    
    # Yapılandırmayı kaydet
    save_config(config)
    
    # Güncellenen işlem sayısını döndür
    return config["admin_actions"][chat_id_str][admin_id_str][action_type]
    
# Anti-flood sistemi için gerekli eklemeler

from collections import defaultdict
from datetime import datetime, timedelta
import asyncio

# Kullanıcıların mesaj zamanlarını ve sayılarını izlemek için veri yapısı
flood_data = defaultdict(lambda: defaultdict(list))

# Anti-flood sistemi için varsayılan yapılandırma
DEFAULT_FLOOD_CONFIG = {
    "enabled": False,           # Anti-flood varsayılan olarak kapalı
    "messages": 5,              # Zaman aralığında izin verilen maksimum mesaj sayısı
    "seconds": 5,               # Mesajların izleneceği zaman aralığı (saniye)
    "action": "mute",           # Flood algılandığında yapılacak eylem (mute, kick, ban, warn, delete)
    "mute_time": 5,             # Mute edilecekse kaç dakika süreyle
    "exclude_admins": True,     # Yöneticileri anti-flood'dan muaf tut
    "warn_only": False,         # Sadece uyarı ver, herhangi bir işlem yapma
    "log_to_channel": True      # Anti-flood olaylarını log kanalında bildir
}

# Anti-flood config ekleme
def add_flood_config_to_group(chat_id):
    """Bir gruba flood koruması yapılandırması ekle"""
    chat_id_str = str(chat_id)
    if chat_id_str not in config["groups"]:
        config["groups"][chat_id_str] = {}
    
    if "flood_settings" not in config["groups"][chat_id_str]:
        config["groups"][chat_id_str]["flood_settings"] = DEFAULT_FLOOD_CONFIG.copy()
        save_config(config)
    
    return config["groups"][chat_id_str]["flood_settings"]

# Anti-flood kontrolü
async def check_flood(event):
    """
    Anti-flood kontrolü yapar, eğer kullanıcı flood yapıyorsa belirlenen eylemi uygular.
    
    :param event: Mesaj olayı
    :return: True (flood algılandı), False (flood algılanmadı)
    """
    if event.is_private:
        return False  # Özel mesajlarda flood kontrolü yapma
    
    # Grup ve kullanıcı ID'leri
    chat_id = event.chat_id
    chat_id_str = str(chat_id)
    user_id = event.sender_id
    
    # Grup flood ayarlarını al, yoksa varsayılan ayarları ekle
    if chat_id_str not in config["groups"] or "flood_settings" not in config["groups"][chat_id_str]:
        flood_settings = add_flood_config_to_group(chat_id)
    else:
        flood_settings = config["groups"][chat_id_str]["flood_settings"]
    
    # Anti-flood devre dışı ise işlem yapma
    if not flood_settings.get("enabled", False):
        return False
    
    # Adminleri hariç tut seçeneği aktif ve kullanıcı admin ise, kontrol etme
    if flood_settings.get("exclude_admins", True) and await is_admin(event.chat, user_id):
        return False
    
    current_time = datetime.now()
    # Son mesajların zamanlarını sakla
    flood_data[chat_id][user_id].append(current_time)
    
    # Belirlenen süreden daha eski mesajları temizle
    time_threshold = current_time - timedelta(seconds=flood_settings.get("seconds", 5))
    flood_data[chat_id][user_id] = [t for t in flood_data[chat_id][user_id] if t > time_threshold]
    
    # Son belirli süre içindeki mesaj sayısını kontrol et
    if len(flood_data[chat_id][user_id]) > flood_settings.get("messages", 5):
        # Flood algılandı, ayarlara göre işlem yap
        action = flood_settings.get("action", "mute")
        
        try:
            # Kullanıcı bilgilerini al
            flooder = await client.get_entity(user_id)
            flooder_name = getattr(flooder, 'first_name', 'Bilinmeyen') + ((' ' + getattr(flooder, 'last_name', '')) if getattr(flooder, 'last_name', '') else '')
            
            # Grup bilgilerini al
            chat = await client.get_entity(chat_id)
            
            # Log metni hazırla
            log_text = f"⚠️ **FLOOD ALGILANDI**\n\n" \
                       f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                       f"**Kullanıcı:** {flooder_name} (`{user_id}`)\n" \
                       f"**Süre içindeki mesaj sayısı:** {len(flood_data[chat_id][user_id])}\n" \
                       f"**Zaman aralığı:** {flood_settings.get('seconds', 5)} saniye\n" \
                       f"**Uygulanan işlem:** {action.upper()}\n" \
                       f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Sadece uyarı seçeneği aktif ve admin değilse, uyarı gönder
            if flood_settings.get("warn_only", False) and not await is_admin(event.chat, user_id):
                await event.respond(f"⚠️ @{flooder.username if hasattr(flooder, 'username') and flooder.username else user_id} Lütfen flood yapmayın!")
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_warn", log_text, None, chat_id)
                
                return True
                
            # Action'a göre işlem yap
            if action.lower() == "mute":
                # Mute işlemi
                mute_time = flood_settings.get("mute_time", 5)  # Dakika cinsinden
                until_date = datetime.now() + timedelta(minutes=mute_time)
                
                await client(EditBannedRequest(
                    chat_id,
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
                
                # İtiraz butonu (önceki değişikliklerdeki gibi)
                appeal_button = Button.url("Susturmaya İtiraz Et", "https://t.me/arayis_itiraz")
                
                # Gruba flood uyarısı gönder
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı {mute_time} dakika susturuldu.",
                    buttons=[[appeal_button]]
                )
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_mute", log_text, None, chat_id)
                
            elif action.lower() == "kick":
                # Kullanıcıyı kickle
                await client(EditBannedRequest(
                    chat_id,
                    user_id,
                    ChatBannedRights(until_date=None, view_messages=True)
                ))
                await client(EditBannedRequest(
                    chat_id,
                    user_id,
                    ChatBannedRights(until_date=None, view_messages=False)
                ))
                
                # İtiraz butonu
                appeal_button = Button.url("Atılmaya İtiraz Et", "https://t.me/arayis_itiraz")
                
                # Gruba flood uyarısı gönder
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı gruptan atıldı.",
                    buttons=[[appeal_button]]
                )
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_kick", log_text, None, chat_id)
                
            elif action.lower() == "ban":
                # Kullanıcıyı banla
                await client(EditBannedRequest(
                    chat_id,
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
                
                # İtiraz butonu
                appeal_button = Button.url("Bana İtiraz Et", "https://t.me/arayis_itiraz")
                
                # Gruba flood uyarısı gönder
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı gruptan banlandı.",
                    buttons=[[appeal_button]]
                )
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_ban", log_text, None, chat_id)
                
            elif action.lower() == "warn":
                # Kullanıcıyı uyar
                await warn_user(event, user_id, "Flood yapmak")
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_warn_system", log_text, None, chat_id)
                
            elif action.lower() == "delete":
                # Sadece mesajı sil
                await event.delete()
                
                # Log kanalına gönder
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_delete", log_text, None, chat_id)
                
            return True
                
        except Exception as e:
            logger.error(f"Anti-flood işlemi sırasında hata: {str(e)}")
            return False
    
    return False


# /setmember komutu ve menüsü için handler
@client.on(events.NewMessage(pattern=r'/setmember'))
async def setmember_menu(event):
    # Yönetici kontrolü
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    # Grup kontrolü
    if event.is_private:
        await event.respond("Bu komut sadece gruplarda kullanılabilir.")
        return
    
    chat = await event.get_chat()
    
    # Menü butonları
    unban_all_button = Button.inline("🔓 Tüm Banları Kaldır", data=f"unban_all_{chat.id}")
    unmute_all_button = Button.inline("🔊 Tüm Muteleri Kaldır", data=f"unmute_all_{chat.id}")
    
    buttons = [
        [unban_all_button],
        [unmute_all_button]
    ]
    
    await event.respond(
        "👥 **Üye İşlemleri Menüsü**\n\n"
        "Bu menüden gruptaki tüm banları veya tüm muteleri kaldırabilirsiniz.\n"
        "⚠️ **Dikkat:** Bu işlemler geri alınamaz!",
        buttons=buttons
    )

# Tüm banları kaldırma butonu için handler
@client.on(events.CallbackQuery(pattern=r'unban_all_(-?\d+)'))
async def unban_all_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "ban"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # Onay butonu
        confirm_button = Button.inline("✅ Evet, Tüm Banları Kaldır", data=f"confirm_unban_all_{chat_id}")
        cancel_button = Button.inline("❌ İptal", data=f"cancel_operation_{chat_id}")
        
        buttons = [
            [confirm_button],
            [cancel_button]
        ]
        
        await event.edit(
            "⚠️ **DİKKAT**\n\n"
            "Bu işlem gruptaki TÜM banlı kullanıcıların banını kaldıracak.\n"
            "Bu işlem geri alınamaz!\n\n"
            "Devam etmek istiyor musunuz?",
            buttons=buttons
        )
    
    except Exception as e:
        logger.error(f"Tüm banları kaldırma işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tüm muteleri kaldırma butonu için handler
@client.on(events.CallbackQuery(pattern=r'unmute_all_(-?\d+)'))
async def unmute_all_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "mute"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # Onay butonu
        confirm_button = Button.inline("✅ Evet, Tüm Muteleri Kaldır", data=f"confirm_unmute_all_{chat_id}")
        cancel_button = Button.inline("❌ İptal", data=f"cancel_operation_{chat_id}")
        
        buttons = [
            [confirm_button],
            [cancel_button]
        ]
        
        await event.edit(
            "⚠️ **DİKKAT**\n\n"
            "Bu işlem gruptaki TÜM susturulmuş kullanıcıların susturmasını kaldıracak.\n"
            "Bu işlem geri alınamaz!\n\n"
            "Devam etmek istiyor musunuz?",
            buttons=buttons
        )
    
    except Exception as e:
        logger.error(f"Tüm muteleri kaldırma işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# İptal butonu için handler
@client.on(events.CallbackQuery(pattern=r'cancel_operation_(-?\d+)'))
async def cancel_operation_handler(event):
    try:
        await event.edit("❌ İşlem iptal edildi.")
    
    except Exception as e:
        logger.error(f"İptal işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tüm banları kaldırma onayı için handler
@client.on(events.CallbackQuery(pattern=r'confirm_unban_all_(-?\d+)'))
async def confirm_unban_all_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "ban"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        await event.edit("🔄 Tüm banlar kaldırılıyor, lütfen bekleyin...")
        
        chat = await client.get_entity(chat_id)
        admin = await event.get_sender()
        
        try:
            # Veritabanımızdaki banlı kullanıcıları bul
            unbanned_count = 0
            failed_count = 0
            
            # "banned_users" anahtar kelimesini yapılandırmada kontrol et
            if "banned_users" not in config:
                config["banned_users"] = {}
                
            if str(chat_id) in config["banned_users"]:
                banned_users = list(config["banned_users"][str(chat_id)].keys())
                
                for user_id_str in banned_users:
                    user_id = int(user_id_str)
                    try:
                        # Banı kaldır
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
                        
                        # Başarılı sayacını artır
                        unbanned_count += 1
                        
                        # Kullanıcıyı banlı listesinden çıkar
                        if user_id_str in config["banned_users"][str(chat_id)]:
                            del config["banned_users"][str(chat_id)][user_id_str]
                            
                    except Exception as e:
                        logger.error(f"Kullanıcı {user_id} banı kaldırılırken hata: {str(e)}")
                        failed_count += 1
                
                # Yapılandırmayı kaydet
                save_config(config)
            
            # İşlem sonucunu bildir
            if unbanned_count > 0:
                result_text = f"✅ **İŞLEM TAMAMLANDI**\n\n" \
                             f"**Grup:** {chat.title}\n" \
                             f"**İşlem:** Toplu ban kaldırma\n" \
                             f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                             f"**Başarılı:** {unbanned_count} kullanıcı\n"
                
                if failed_count > 0:
                    result_text += f"**Başarısız:** {failed_count} kullanıcı\n"
                
                result_text += f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                # Sonucu göster
                await event.edit(result_text)
                
                # Log kanalına bildir
                await log_to_thread("ban", result_text, None, chat_id)
            else:
                await event.edit("ℹ️ Banlı kullanıcı bulunamadı veya tüm işlemler başarısız oldu.")
        
        except Exception as e:
            logger.error(f"Tüm banları kaldırma işleminde hata: {str(e)}")
            await event.edit(f"❌ İşlem sırasında bir hata oluştu: {str(e)}")
    
    except Exception as e:
        logger.error(f"Ban kaldırma onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tüm muteleri kaldırma onayı için handler
@client.on(events.CallbackQuery(pattern=r'confirm_unmute_all_(-?\d+)'))
async def confirm_unmute_all_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "mute"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        await event.edit("🔄 Tüm muteler kaldırılıyor, lütfen bekleyin...")
        
        chat = await client.get_entity(chat_id)
        admin = await event.get_sender()
        
        try:
            # Veritabanımızdaki susturulmuş kullanıcıları bul
            unmuted_count = 0
            failed_count = 0
            
            # "muted_users" anahtar kelimesini yapılandırmada kontrol et
            if "muted_users" not in config:
                config["muted_users"] = {}
                
            if str(chat_id) in config["muted_users"]:
                muted_users = list(config["muted_users"][str(chat_id)].keys())
                
                for user_id_str in muted_users:
                    user_id = int(user_id_str)
                    try:
                        # Susturmayı kaldır
                        await client(EditBannedRequest(
                            chat_id,
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
                        
                        # Başarılı sayacını artır
                        unmuted_count += 1
                        
                        # Kullanıcıyı susturulmuş listesinden çıkar
                        if user_id_str in config["muted_users"][str(chat_id)]:
                            del config["muted_users"][str(chat_id)][user_id_str]
                            
                    except Exception as e:
                        logger.error(f"Kullanıcı {user_id} susturması kaldırılırken hata: {str(e)}")
                        failed_count += 1
                
                # Yapılandırmayı kaydet
                save_config(config)
            
            # İşlem sonucunu bildir
            if unmuted_count > 0:
                result_text = f"✅ **İŞLEM TAMAMLANDI**\n\n" \
                             f"**Grup:** {chat.title}\n" \
                             f"**İşlem:** Toplu susturma kaldırma\n" \
                             f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                             f"**Başarılı:** {unmuted_count} kullanıcı\n"
                
                if failed_count > 0:
                    result_text += f"**Başarısız:** {failed_count} kullanıcı\n"
                
                result_text += f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                # Sonucu göster
                await event.edit(result_text)
                
                # Log kanalına bildir
                await log_to_thread("mute", result_text, None, chat_id)
            else:
                await event.edit("ℹ️ Susturulmuş kullanıcı bulunamadı veya tüm işlemler başarısız oldu.")
        
        except Exception as e:
            logger.error(f"Tüm muteleri kaldırma işleminde hata: {str(e)}")
            await event.edit(f"❌ İşlem sırasında bir hata oluştu: {str(e)}")
    
    except Exception as e:
        logger.error(f"Mute kaldırma onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)


# Report komutu - Adminlere mesaj rapor etme sistemi
# Report komutu - Adminlere mesaj rapor etme sistemi (hata düzeltmesiyle)
# Report komutu - Adminlere mesaj rapor etme sistemi (geliştirilmiş versiyon)
# Report komutu - Adminlere mesaj rapor etme sistemi (düzeltilmiş versiyon)
# Report komutu - Adminlere mesaj rapor etme sistemi (tek mesajda etiketleme)
@client.on(events.NewMessage(pattern=r'/report(?:@\w+)?(?:\s+(.+))?'))
async def report_command(event):
    # Özel mesajlarda çalışmaz
    if event.is_private:
        await event.respond("Bu komut sadece gruplarda kullanılabilir.")
        return
    
    try:
        chat = await event.get_chat()
        reporter = await event.get_sender()
        reason = event.pattern_match.group(1)
        reply_message = None
        
        # Eğer bir mesaja yanıt verilmişse, o mesajı al
        if event.reply_to:
            try:
                reply_message = await event.get_reply_message()
            except Exception as e:
                logger.error(f"Yanıt verilen mesajı alırken hata: {str(e)}")
                reply_message = None
        
        # Eğer yanıt yoksa ve sebep belirtilmemişse, sebep iste ve bitir
        if not reply_message and not reason:
            await event.respond("Lütfen bir sebep belirtin veya bir mesaja yanıt verin.\nÖrnek: `/report spam mesajlar atıyor`")
            return
        
        # Alternatif yöntem ile grup adminlerini al
        admin_list = []
        admin_mentions = []
        
        try:
            # Doğrudan tüm katılımcıları al
            admins = []
            async for user in client.iter_participants(chat):
                try:
                    # Botun bir parçası olan katılımcıları getir
                    participant = await client(GetParticipantRequest(
                        chat.id,
                        user.id
                    ))
                    
                    # Admin veya kurucu ise listeye ekle
                    if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                        if not user.bot:
                            admins.append(user)
                except Exception as e:
                    # Bu kullanıcı için hata oluşursa atla
                    continue
            
            # Eğer hiç admin bulunamazsa, bu yaklaşımı dene
            if not admins:
                try:
                    # Son çare: Grup yaratıcısını veya kendinizi admin olarak kullanın
                    chat_full = await client(GetFullChannelRequest(chat.id))
                    
                    if hasattr(chat_full, 'full_chat') and hasattr(chat_full.full_chat, 'participants_count'):
                        # Basitçe rapor eden kişiyi ekleyin (başka bir admin bulunamadı)
                        admins.append(reporter)
                except Exception as e:
                    logger.error(f"Grup bilgisini alırken hata: {str(e)}")
                    # Rapor eden kişiyi admin olarak ekle
                    admins.append(reporter)
            
            # Admin listesini hazırla
            for admin in admins:
                admin_list.append(admin)
                admin_mentions.append(f"[{admin.first_name}](tg://user?id={admin.id})")
                
        except Exception as e:
            logger.error(f"Adminleri alırken hata: {str(e)}")
            # Hata durumunda basitleştirilmiş yaklaşım kullan - yalnızca raporu oluşturan kişiyi admin olarak ekle
            admin_list.append(reporter)
            admin_mentions.append(f"[{reporter.first_name}](tg://user?id={reporter.id})")
        
        # Admin yoksa basit bir mesaj göster ve devam et
        if not admin_list:
            admin_list.append(reporter)  # En azından rapor eden kişiye bildirim gönder
            admin_mentions.append(f"[{reporter.first_name}](tg://user?id={reporter.id})")
        
        # Raporlanacak mesajı ve bilgileri hazırla
        reported_user_name = "Bilinmeyen Kullanıcı"
        reported_user_id = 0
        message_link = None
        message_text = "[Metin içeriği yok]"
        
        if reply_message:
            try:
                # Rapor edilen kullanıcı bilgisini al
                reported_user = await reply_message.get_sender()
                if reported_user:
                    reported_user_name = reported_user.first_name
                    reported_user_id = reported_user.id
                
                # Mesaj linkini oluştur
                if hasattr(reply_message, 'id'):
                    # Grup ID'sinden 100 çıkar (Telegram API formatı için)
                    chat_id_for_link = str(chat.id).replace('-100', '')
                    message_link = f"https://t.me/c/{chat_id_for_link}/{reply_message.id}"
                
                # Mesaj içeriğini al
                if hasattr(reply_message, 'text') and reply_message.text:
                    message_text = reply_message.text[:1000]  # Mesajı 1000 karakterle sınırla
                    # Mesaj çok uzunsa bunu belirt
                    if len(reply_message.text) > 1000:
                        message_text += "...\n[Mesaj çok uzun, kısaltıldı]"
            except Exception as e:
                logger.error(f"Rapor edilecek mesaj bilgilerini alırken hata: {str(e)}")
        
        # DM için rapor mesajını hazırla (mention kullanarak)
        dm_report_text = f"📢 **YENİ RAPOR**\n\n" \
                        f"**Grup:** {chat.title}\n" \
                        f"**Rapor Eden:** [{reporter.first_name}](tg://user?id={reporter.id})\n"
                        
        if reply_message:
            dm_report_text += f"**Rapor Edilen:** [{reported_user_name}](tg://user?id={reported_user_id})\n"
                
        if reason:
            dm_report_text += f"**Sebep:** {reason}\n\n"
            
        if reply_message:
            dm_report_text += f"**Rapor Edilen Mesaj:**\n{message_text}"
            
            # Eğer rapor edilen mesajda medya varsa bunu da belirt
            if hasattr(reply_message, 'media') and reply_message.media:
                dm_report_text += "\n[Mesajda medya içeriği bulunmaktadır]"
        
        # Adminlere DM ile rapor gönder
        for admin in admin_list:
            try:
                if admin.id != reporter.id:  # Rapor eden kişi adminse kendisine DM gönderme
                    # Mesaj link butonu ekle
                    buttons = None
                    if message_link:
                        buttons = [Button.url("📝 Mesaja Git", message_link)]
                    
                    # Her admine DM göndermeyi dene
                    await client.send_message(
                        admin.id, 
                        dm_report_text, 
                        parse_mode='md',
                        buttons=buttons
                    )
            except Exception as e:
                # DM gönderilemezse hata kaydet ama devam et
                logger.error(f"Admin {admin.id}'e DM gönderilirken hata: {str(e)}")
        
        # Grupta adminleri tek mesajda etiketleyerek gönder
        try:
            # Tüm admin etiketlerini tek bir string'e birleştir
            admin_tags = " ".join(admin_mentions)
            
            # Rapor mesajını oluştur
            group_report = f"⚠️ **DİKKAT ADMİNLER** ⚠️\n\n" \
                        f"**Rapor Eden:** [{reporter.first_name}](tg://user?id={reporter.id})\n"
            
            if reply_message:
                group_report += f"**Rapor Edilen:** [{reported_user_name}](tg://user?id={reported_user_id})\n"
            
            if reason:
                group_report += f"**Sebep:** {reason}\n"
                
            # Tüm adminleri etiketle
            group_report += f"\n{admin_tags}"
            
            # Rapor mesajını gönder
            report_msg = await event.respond(group_report, parse_mode='md')
            
            # Birkaç saniye bekle (adminlerin bildirim alması için)
            await asyncio.sleep(1)
            
            # Rapor mesajını düzenle
            try:
                await report_msg.edit("✅ **Rapor adminlere bildirildi!**", parse_mode='md')
            except Exception as e:
                logger.error(f"Rapor mesajını düzenlerken hata: {str(e)}")
            
            # Orijinal komutu temizle
            try:
                await event.delete()
            except:
                pass
        except Exception as e:
            logger.error(f"Grup içinde adminleri etiketlerken hata: {str(e)}")
            await event.respond("Rapor adminlere bildirildi!")
            
    except Exception as e:
        logger.error(f"Rapor gönderme sırasında genel hata: {str(e)}")
        await event.respond("Rapor adminlere bildirildi!")  # Basit ve net bir mesaj
        
# Ana fonksiyon
async def main():
    load_stats()
    # Anti-flood ayarlarını başlat
    for chat_id_str in config["groups"]:
        # Anti-flood ayarı yoksa ekle
        if "flood_settings" not in config["groups"][chat_id_str]:
            config["groups"][chat_id_str]["flood_settings"] = DEFAULT_FLOOD_CONFIG.copy()
    
    # Tekrarlanan mesajlar için arka plan görevi
    asyncio.create_task(send_repeated_messages())
    asyncio.create_task(send_daily_report())
    print("Bot çalışıyor!")
    
    # Bot sonsuza kadar çalışsın
    await client.run_until_disconnected()

# Bot'u başlat
with client:
    client.loop.run_until_complete(main())
