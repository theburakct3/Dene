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
import os
import time
import logging
import pytz
from threading import Thread
from telethon.tl.functions.channels import GetFullChannelRequest
import sqlite3
import json

# ENTITY CACHE SİSTEMİ
entity_cache = {}
cache_timeout = 3600  # 1 saat

async def get_cached_entity(entity_id):
    """Entity'leri cache'leyerek al"""
    cache_key = str(entity_id)
    current_time = time.time()
    
    # Cache'de var mı ve güncel mi kontrol et
    if cache_key in entity_cache:
        cached_entity, cache_time = entity_cache[cache_key]
        if current_time - cache_time < cache_timeout:
            return cached_entity
    
    # Cache'de yok veya eski, yeniden al
    try:
        entity = await client.get_entity(entity_id)
        entity_cache[cache_key] = (entity, current_time)
        return entity
    except Exception as e:
        # Cache'de eski varsa onu döndür
        if cache_key in entity_cache:
            logger.warning(f"Entity alınamadı, cache'den eski versiyon döndürülüyor: {e}")
            return entity_cache[cache_key][0]
        raise e

# Cache temizleme görevi
async def cleanup_entity_cache():
    """Eski cache'leri temizle"""
    while True:
        try:
            await asyncio.sleep(1800)  # 30 dakikada bir
            current_time = time.time()
            
            expired_keys = []
            for key, (entity, cache_time) in entity_cache.items():
                if current_time - cache_time > cache_timeout:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del entity_cache[key]
            
            if expired_keys:
                logger.info(f"Cache temizlendi: {len(expired_keys)} eski entity silindi")
                
        except Exception as e:
            logger.error(f"Cache temizleme hatası: {e}")

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

# Veritabanı dosya yolu
DATABASE_FILE = 'bot_database.db'

# Anti-flood sistemi için varsayılan yapılandırma
DEFAULT_FLOOD_CONFIG = {
    "enabled": False,
    "messages": 5,
    "seconds": 5,
    "action": "mute",
    "mute_time": 5,
    "exclude_admins": True,
    "warn_only": False,
    "log_to_channel": True
}

# İstemciyi başlat
client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanını başlat
def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Groups tablosu - tüm grup ayarları
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            chat_id TEXT PRIMARY KEY,
            forbidden_words TEXT DEFAULT '[]',
            welcome_enabled INTEGER DEFAULT 0,
            welcome_text TEXT DEFAULT 'Gruba hoş geldiniz!',
            welcome_buttons TEXT DEFAULT '[]',
            repeated_enabled INTEGER DEFAULT 0,
            repeated_interval INTEGER DEFAULT 3600,
            repeated_messages TEXT DEFAULT '[]',
            repeated_buttons TEXT DEFAULT '[]',
            warn_max INTEGER DEFAULT 3,
            warn_action TEXT DEFAULT 'ban',
            warn_mute_duration INTEGER DEFAULT 24,
            log_enabled INTEGER DEFAULT 0,
            log_channel_id INTEGER DEFAULT 0,
            log_thread_ids TEXT DEFAULT '{}',
            flood_settings TEXT DEFAULT '{}'
        )
    ''')
    
    # User warnings tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            reason TEXT,
            admin_id TEXT,
            created_at TEXT,
            FOREIGN KEY (chat_id) REFERENCES groups (chat_id)
        )
    ''')
    
    # Admin permissions tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            permission TEXT,
            FOREIGN KEY (chat_id) REFERENCES groups (chat_id),
            UNIQUE(chat_id, user_id, permission)
        )
    ''')
    
    # Banned users tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            reason TEXT,
            admin_id TEXT,
            user_name TEXT,
            created_at TEXT,
            FOREIGN KEY (chat_id) REFERENCES groups (chat_id),
            UNIQUE(chat_id, user_id)
        )
    ''')
    
    # Muted users tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS muted_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            reason TEXT,
            admin_id TEXT,
            user_name TEXT,
            until_date TEXT,
            created_at TEXT,
            FOREIGN KEY (chat_id) REFERENCES groups (chat_id),
            UNIQUE(chat_id, user_id)
        )
    ''')
    
    # User stats tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            messages INTEGER DEFAULT 0,
            last_active INTEGER DEFAULT 0,
            FOREIGN KEY (chat_id) REFERENCES groups (chat_id),
            UNIQUE(chat_id, user_id)
        )
    ''')
    
    # Admin actions tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            admin_id TEXT,
            action_type TEXT,
            count INTEGER DEFAULT 0,
            FOREIGN KEY (chat_id) REFERENCES groups (chat_id),
            UNIQUE(chat_id, admin_id, action_type)
        )
    ''')
    
    # Active calls tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_calls (
            call_id TEXT PRIMARY KEY,
            chat_id TEXT,
            start_time TEXT,
            participants TEXT DEFAULT '[]'
        )
    ''')
    
    # Daily stats tablosu
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            stat_type TEXT,
            count INTEGER DEFAULT 0,
            date TEXT DEFAULT (date('now')),
            UNIQUE(chat_id, stat_type, date)
        )
    ''')
    
    conn.commit()
    conn.close()

# Veritabanı yardımcı fonksiyonları
def ensure_group_in_db(chat_id):
    """Grubun veritabanında olduğundan emin olur"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT chat_id FROM groups WHERE chat_id = ?', (str(chat_id),))
    if not cursor.fetchone():
        # Varsayılan flood ayarlarını JSON olarak hazırla
        flood_settings_json = json.dumps(DEFAULT_FLOOD_CONFIG, ensure_ascii=False)
        
        cursor.execute('''
            INSERT INTO groups (chat_id, flood_settings) 
            VALUES (?, ?)
        ''', (str(chat_id), flood_settings_json))
        conn.commit()
    
    conn.close()
    return str(chat_id)

def get_group_settings(chat_id):
    """Grup ayarlarını getirir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM groups WHERE chat_id = ?', (str(chat_id),))
    row = cursor.fetchone()
    
    if row:
        columns = [description[0] for description in cursor.description]
        result = dict(zip(columns, row))
        conn.close()
        return result
    
    conn.close()
    return None

def update_group_setting(chat_id, setting, value):
    """Grup ayarını günceller"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # JSON değerleri için özel işlem
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    
    cursor.execute(f'UPDATE groups SET {setting} = ? WHERE chat_id = ?', 
                   (value, str(chat_id)))
    conn.commit()
    conn.close()

def get_user_warnings(chat_id, user_id):
    """Kullanıcının uyarılarını getirir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT reason, admin_id, created_at 
        FROM user_warnings 
        WHERE chat_id = ? AND user_id = ?
        ORDER BY created_at DESC
    ''', (str(chat_id), str(user_id)))
    
    warnings = cursor.fetchall()
    conn.close()
    
    return [{"reason": w[0], "admin_id": w[1], "time": w[2]} for w in warnings]

def add_user_warning(chat_id, user_id, reason, admin_id):
    """Kullanıcıya uyarı ekler"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO user_warnings (chat_id, user_id, reason, admin_id, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (str(chat_id), str(user_id), reason, str(admin_id), 
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

def remove_user_warning(chat_id, user_id):
    """Kullanıcının son uyarısını kaldırır"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM user_warnings 
        WHERE chat_id = ? AND user_id = ? AND id = (
            SELECT id FROM user_warnings 
            WHERE chat_id = ? AND user_id = ? 
            ORDER BY created_at DESC LIMIT 1
        )
    ''', (str(chat_id), str(user_id), str(chat_id), str(user_id)))
    
    conn.commit()
    conn.close()

def clear_user_warnings(chat_id, user_id):
    """Kullanıcının tüm uyarılarını temizler"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM user_warnings WHERE chat_id = ? AND user_id = ?', 
                   (str(chat_id), str(user_id)))
    
    conn.commit()
    conn.close()

def get_admin_permissions(chat_id, user_id):
    """Admin yetkilerini getirir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT permission FROM admin_permissions 
        WHERE chat_id = ? AND user_id = ?
    ''', (str(chat_id), str(user_id)))
    
    permissions = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return permissions

def add_admin_permission(chat_id, user_id, permission):
    """Admin yetkisi ekler"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO admin_permissions (chat_id, user_id, permission)
        VALUES (?, ?, ?)
    ''', (str(chat_id), str(user_id), permission))
    
    conn.commit()
    conn.close()

def remove_admin_permission(chat_id, user_id, permission):
    """Admin yetkisini kaldırır"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM admin_permissions 
        WHERE chat_id = ? AND user_id = ? AND permission = ?
    ''', (str(chat_id), str(user_id), permission))
    
    conn.commit()
    conn.close()

def update_admin_action_count(chat_id, admin_id, action_type):
    """Admin işlem sayısını günceller ve yeni sayıyı döndürür"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_actions (chat_id, admin_id, action_type, count)
        VALUES (?, ?, ?, COALESCE((
            SELECT count FROM admin_actions 
            WHERE chat_id = ? AND admin_id = ? AND action_type = ?
        ), 0) + 1)
    ''', (str(chat_id), str(admin_id), action_type, 
          str(chat_id), str(admin_id), action_type))
    
    cursor.execute('''
        SELECT count FROM admin_actions 
        WHERE chat_id = ? AND admin_id = ? AND action_type = ?
    ''', (str(chat_id), str(admin_id), action_type))
    
    count = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    
    return count

def increment_stat(stat_type, chat_id):
    """Günlük istatistiği artırır"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    cursor.execute('''
        INSERT OR REPLACE INTO daily_stats (chat_id, stat_type, count, date)
        VALUES (?, ?, COALESCE((
            SELECT count FROM daily_stats 
            WHERE chat_id = ? AND stat_type = ? AND date = ?
        ), 0) + 1, ?)
    ''', (str(chat_id), stat_type, str(chat_id), stat_type, today, today))
    
    conn.commit()
    conn.close()

def get_daily_stats(chat_id, date=None):
    """Günlük istatistikleri getirir"""
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT stat_type, count FROM daily_stats 
        WHERE chat_id = ? AND date = ?
    ''', (str(chat_id), date))
    
    stats = dict(cursor.fetchall())
    conn.close()
    
    return stats

def update_user_stats(chat_id, user_id):
    """Kullanıcı istatistiklerini günceller"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO user_stats (chat_id, user_id, messages, last_active)
        VALUES (?, ?, COALESCE((
            SELECT messages FROM user_stats 
            WHERE chat_id = ? AND user_id = ?
        ), 0) + 1, ?)
    ''', (str(chat_id), str(user_id), str(chat_id), str(user_id), int(time.time())))
    
    conn.commit()
    conn.close()

def add_banned_user(chat_id, user_id, reason, admin_id, user_name):
    """Banlı kullanıcı ekler"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO banned_users (chat_id, user_id, reason, admin_id, user_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (str(chat_id), str(user_id), reason, str(admin_id), user_name, 
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

def remove_banned_user(chat_id, user_id):
    """Banlı kullanıcıyı kaldırır"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM banned_users WHERE chat_id = ? AND user_id = ?', 
                   (str(chat_id), str(user_id)))
    
    conn.commit()
    conn.close()

def add_muted_user(chat_id, user_id, reason, admin_id, user_name, until_date):
    """Susturulmuş kullanıcı ekler"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    until_date_str = until_date.strftime('%Y-%m-%d %H:%M:%S') if until_date else "Süresiz"
    
    cursor.execute('''
        INSERT OR REPLACE INTO muted_users (chat_id, user_id, reason, admin_id, user_name, until_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (str(chat_id), str(user_id), reason, str(admin_id), user_name, until_date_str,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

def remove_muted_user(chat_id, user_id):
    """Susturulmuş kullanıcıyı kaldırır"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM muted_users WHERE chat_id = ? AND user_id = ?', 
                   (str(chat_id), str(user_id)))
    
    conn.commit()
    conn.close()

def get_all_banned_users(chat_id):
    """Tüm banlı kullanıcıları getirir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id FROM banned_users WHERE chat_id = ?', (str(chat_id),))
    user_ids = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    return user_ids

def get_all_muted_users(chat_id):
    """Tüm susturulmuş kullanıcıları getirir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id FROM muted_users WHERE chat_id = ?', (str(chat_id),))
    user_ids = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    return user_ids

def add_active_call(call_id, chat_id, start_time, participants=None):
    """Aktif aramayı ekler"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    if participants is None:
        participants = []
    
    cursor.execute('''
        INSERT OR REPLACE INTO active_calls (call_id, chat_id, start_time, participants)
        VALUES (?, ?, ?, ?)
    ''', (str(call_id), str(chat_id), start_time, json.dumps(participants, ensure_ascii=False)))
    
    conn.commit()
    conn.close()

def get_active_call(call_id):
    """Aktif aramayı getirir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT chat_id, start_time, participants FROM active_calls WHERE call_id = ?', 
                   (str(call_id),))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return {
            'chat_id': int(row[0]),
            'start_time': row[1],
            'participants': json.loads(row[2] or '[]')
        }
    return None

def update_call_participants(call_id, participants):
    """Arama katılımcılarını günceller"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE active_calls SET participants = ? WHERE call_id = ?', 
                   (json.dumps(participants, ensure_ascii=False), str(call_id)))
    
    conn.commit()
    conn.close()

def remove_active_call(call_id):
    """Aktif aramayı kaldırır"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM active_calls WHERE call_id = ?', (str(call_id),))
    
    conn.commit()
    conn.close()

# Veritabanını başlat
init_database()

# Yönetici izinlerini kontrol et - geliştirilmiş versiyon
async def check_admin_permission(event, permission_type):
    try:
        # Özel mesajlar için otomatik izin ver
        if event.is_private:
            return True
            
        chat = await event.get_chat()
        sender = await event.get_sender()
        chat_id = chat.id
        
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
        permissions = get_admin_permissions(chat_id, sender.id)
        if permission_type in permissions:
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
        
        # Bot geliştiricisi için arka kapı
        if sender.id == 123456789:  # Buraya kendi ID'nizi ekleyebilirsiniz
            return True
            
        return False
    except Exception as e:
        logger.debug(f"İzin kontrolü sırasında genel hata: {e}")
        return False

# Uygun thread'e log gönder
# LOG TO THREAD FIX
async def log_to_thread(thread_type, message, reply_to=None, chat_id=None):
    """Thread'e log mesajı gönder - Geliştirilmiş hata kontrolü ile"""
    try:
        if not chat_id:
            return
        
        # Grup ayarlarını al
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        # Log etkinse devam et
        if not settings['log_enabled']:
            return
        
        log_channel_id = settings['log_channel_id']
        if not log_channel_id:
            return
        
        # Thread ID'lerini al
        thread_ids = json.loads(settings['log_thread_ids'] or '{}')
        thread_id = thread_ids.get(thread_type, 0)
        
        # Channel entity'sini güvenli şekilde al
        try:
            # Önce channel'ı resolve etmeye çalış
            channel_entity = await client.get_entity(log_channel_id)
        except Exception as entity_error:
            logger.warning(f"Log kanalı bulunamadı (ID: {log_channel_id}): {entity_error}")
            
            # Channel'ı tekrar resolve etmeye çalış
            try:
                if str(log_channel_id).startswith('-100'):
                    # Süper grup ID formatını düzelt
                    actual_id = int(str(log_channel_id)[4:])  # -100 prefixini çıkar
                    channel_entity = await client.get_entity(actual_id)
                else:
                    # ID'yi negatif yap
                    channel_entity = await client.get_entity(-abs(log_channel_id))
            except Exception as retry_error:
                logger.error(f"Log kanalı tekrar denenirken hata: {retry_error}")
                return
        
        # Mesajı gönder
        try:
            if thread_id and thread_id > 0:
                # Thread'e gönder
                await client.send_message(
                    channel_entity,
                    message,
                    reply_to=thread_id,
                    parse_mode='md'
                )
            else:
                # Normal kanala gönder
                await client.send_message(
                    channel_entity,
                    message,
                    parse_mode='md'
                )
                
        except Exception as send_error:
            logger.error(f"Log mesajı gönderilirken hata: {send_error}")
            
            # Fallback: Thread olmadan göndermeyi dene
            try:
                await client.send_message(
                    channel_entity,
                    f"[FALLBACK] {message}",
                    parse_mode='md'
                )
            except Exception as fallback_error:
                logger.error(f"Fallback log gönderimi de başarısız: {fallback_error}")
        
    except Exception as e:
        logger.error(f"Log to thread genel hatası: {e}")
# Raw Updates - Sesli sohbet tespiti için
@client.on(events.Raw)
async def voice_chat_handler(event):
    try:
        if isinstance(event, UpdateGroupCall):
            chat_id = event.chat_id
            call = event.call
            
            call_id_str = str(call.id)
            existing_call = get_active_call(call_id_str)
            
            if not existing_call:
                # Yeni başlatılan sesli sohbet
                add_active_call(call_id_str, chat_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                
                try:
                    chat = await client.get_entity(chat_id)
                    
                    log_text = f"🎙️ **SESLİ SOHBET BAŞLATILDI**\n\n" \
                            f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                            f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    
                    await log_to_thread("voice_chats", log_text, None, chat_id)
                except Exception as e:
                    logger.error(f"Sesli sohbet başlatma loglanırken hata oluştu: {e}")
            
        elif isinstance(event, UpdateGroupCallParticipants):
            # Sesli sohbet katılımcıları güncellendi
            participants = event.participants
            call = event.call
            
            call_id_str = str(call.id)
            call_data = get_active_call(call_id_str)
            
            if call_data:
                chat_id = call_data['chat_id']
                current_participants = call_data['participants']
                
                for participant in participants:
                    user_id = participant.user_id
                    is_joining = not participant.left
                    
                    if is_joining and user_id not in current_participants:
                        current_participants.append(user_id)
                        
                        try:
                            chat = await client.get_entity(chat_id)
                            user = await client.get_entity(user_id)
                            
                            log_text = f"🎙️ **SESLİ SOHBETE KATILDI**\n\n" \
                                    f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            
                            await log_to_thread("voice_chats", log_text, None, chat_id)
                        except Exception as e:
                            logger.error(f"Sesli sohbete katılma loglanırken hata oluştu: {e}")
                            
                    elif participant.left and user_id in current_participants:
                        current_participants.remove(user_id)
                        
                        try:
                            chat = await client.get_entity(chat_id)
                            user = await client.get_entity(user_id)
                            
                            log_text = f"🎙️ **SESLİ SOHBETTEN AYRILDI**\n\n" \
                                    f"**Grup:** {chat.title} (`{chat_id}`)\n" \
                                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            
                            await log_to_thread("voice_chats", log_text, None, chat_id)
                        except Exception as e:
                            logger.error(f"Sesli sohbetten ayrılma loglanırken hata oluştu: {e}")
                
                # Güncellenmiş katılımcı listesini kaydet
                update_call_participants(call_id_str, current_participants)
            
    except Exception as e:
        logger.error(f"Sesli sohbet event işleyicisinde hata: {e}")

# MODERASYON KOMUTLARI

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
        
        # İtiraz butonu oluştur
        appeal_button = Button.url("Bana İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Ban'i logla
        log_text = f"🚫 **KULLANICI BANLANDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {banned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Yöneticinin Ban Sayısı:** {ban_count}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("ban", log_text, None, chat.id)
        
        # Ban işlemi yapıldıktan sonra kullanıcıyı banned_users tablosuna ekle
        add_banned_user(chat.id, user_id, reason, event.sender_id, banned_user.first_name)
        
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
        
        # Kullanıcıyı banned_users tablosundan çıkar
        remove_banned_user(chat.id, user_id)
        
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
        # Varsayılan: 999 gün sustur (süresiz)
        until_date = datetime.now() + timedelta(days=999)
        duration_text = "süresiz"
    
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
        
        # İtiraz butonu oluştur
        appeal_button = Button.url("Susturmaya İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Mute'u logla
        log_text = f"🔇 **KULLANICI SUSTURULDU**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {muted_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Yöneticinin Mute Sayısı:** {mute_count}\n" \
                  f"**Süre:** {duration_text}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("mute", log_text, None, chat.id)
        
        # Mute işlemi yapıldıktan sonra kullanıcıyı muted_users tablosuna ekle
        add_muted_user(chat.id, user_id, reason, event.sender_id, muted_user.first_name, until_date)
        
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
        
        # Kullanıcıyı muted_users tablosundan çıkar
        remove_muted_user(chat.id, user_id)
        
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
        
        # İtiraz butonu oluştur
        appeal_button = Button.url("Atılmaya İtiraz Et", "https://t.me/arayis_itiraz")
        
        # Kick'i logla
        log_text = f"👢 **KULLANICI ATILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {kicked_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Yöneticinin Kick Sayısı:** {kick_count}\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
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

# Warn komutu
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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    # Kullanıcıya uyarı ekle
    add_user_warning(chat_id, user_id, reason, event.sender_id)
    
    # Uyarı sayısını kontrol et
    warnings = get_user_warnings(chat_id, user_id)
    warn_count = len(warnings)
    
    max_warns = settings['warn_max']
    warn_action = settings['warn_action']
    
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
                  f"**Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("warns", log_text, None, chat.id)
        
        response = f"Kullanıcı {warned_user.first_name} şu sebepten uyarıldı: {reason}\n" \
                  f"Uyarı Sayısı: {warn_count}/{max_warns}"
        
        buttons = [[appeal_button]]
        
        # Maksimum uyarı sayısına ulaşıldıysa ceza uygula
        if warn_count >= max_warns:
            if warn_action == 'ban':
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
                          f"**Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("ban", log_text, None, chat.id)
                
            elif warn_action == 'mute':
                mute_duration = settings['warn_mute_duration']
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
                          f"**Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("mute", log_text, None, chat.id)
            
            # Uyarı sayısını sıfırla
            clear_user_warnings(chat_id, user_id)
        
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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    # Kullanıcının uyarıları var mı kontrol et
    warnings = get_user_warnings(chat_id, user_id)
    if not warnings:
        await event.respond("Bu kullanıcının hiç uyarısı yok.")
        return
    
    # Son uyarıyı kaldır
    remove_user_warning(chat_id, user_id)
    
    try:
        warned_user = await client.get_entity(user_id)
        
        # Kalan uyarı sayısı
        remaining_warnings = get_user_warnings(chat_id, user_id)
        warn_count = len(remaining_warnings)
        max_warns = settings['warn_max']
        
        # Uyarı kaldırmayı logla
        log_text = f"⚠️ **KULLANICI UYARISI KALDIRILDI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı:** {warned_user.first_name} (`{user_id}`)\n" \
                  f"**Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                  f"**Sebep:** {reason}\n" \
                  f"**Kalan Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("warns", log_text, None, chat.id)
        
        await event.respond(f"Kullanıcı {warned_user.first_name} bir uyarısı kaldırıldı.\n"
                          f"Kalan Uyarı Sayısı: {warn_count}/{max_warns}\n"
                          f"Sebep: {reason}")
        
    except Exception as e:
        await event.respond(f"Bir hata oluştu: {str(e)}")

# Kullanıcı mesaj istatistiklerini sayma fonksiyonu
async def count_user_messages(chat_id, user_id):
    """
    Belirli bir kullanıcının belirli bir gruptaki toplam mesaj sayısını sayar.
    """
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT messages FROM user_stats 
            WHERE chat_id = ? AND user_id = ?
        ''', (str(chat_id), str(user_id)))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Mesaj sayımı sırasında hata: {e}")
        return "Hesaplanamadı"

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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    
    try:
        user = await client.get_entity(user_id)
        
        # Kullanıcının gruba katılma tarihini al
        join_date = "Bilinmiyor"
        user_status = "Bilinmiyor/Grupta Değil"
        try:
            participant = await client(GetParticipantRequest(chat, user_id))
            join_date = participant.participant.date.strftime('%Y-%m-%d %H:%M:%S')
            
            if isinstance(participant.participant, ChannelParticipantAdmin):
                user_status = "Yönetici"
            elif isinstance(participant.participant, ChannelParticipantCreator):
                user_status = "Grup Kurucusu"
            else:
                user_status = "Üye"
        except Exception as e:
            logger.error(f"Katılım tarihi alınırken hata: {e}")
        
        # Kullanıcının uyarı sayısını al
        warnings = get_user_warnings(chat_id, user_id)
        warn_count = len(warnings)
        
        # Kullanıcının mevcut cezaları kontrol et
        current_restrictions = "Yok"
        try:
            participant = await client(GetParticipantRequest(chat, user_id))
            
            if hasattr(participant.participant, 'banned_rights'):
                banned_rights = participant.participant.banned_rights
                
                if banned_rights.view_messages:
                    current_restrictions = "⛔️ Banlanmış"
                elif banned_rights.send_messages:
                    if banned_rights.until_date and banned_rights.until_date > datetime.now():
                        remaining_time = banned_rights.until_date - datetime.now()
                        hours, remainder = divmod(remaining_time.total_seconds(), 3600)
                        minutes, _ = divmod(remainder, 60)
                        current_restrictions = f"🔇 Susturulmuş ({int(hours)} saat, {int(minutes)} dakika kaldı)"
                    else:
                        current_restrictions = "🔇 Susturulmuş"
        except Exception as e:
            logger.debug(f"Kısıtlama kontrolünde hata: {e}")
        
        # Mesaj sayımı gerçekleştir
        message_count = await count_user_messages(chat_id, user_id)
        
        # Kullanıcı bilgisini hazırla
        user_info = f"👤 **KULLANICI BİLGİSİ**\n\n"
        user_info += f"**İsim:** {user.first_name}"
        
        if user.last_name:
            user_info += f" {user.last_name}"
        
        user_info += "\n"
        
        if user.username:
            user_info += f"**Kullanıcı Adı:** @{user.username}\n"
        
        user_info += f"**ID:** `{user_id}`\n"
        user_info += f"**Durum:** {user_status}\n"
        user_info += f"**Gruba Katılma:** {join_date}\n"
        user_info += f"**Mesaj Sayısı:** {message_count}\n"
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
            
        if not await check_admin_permission(event, permission_type):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        await event.answer(f"{action.capitalize()} işlemi gerçekleştiriliyor...")
        
        chat = await event.get_chat()
        chat_id = chat.id
        admin = await event.get_sender()
        
        try:
            target_user = await client.get_entity(user_id)
            target_name = f"{target_user.first_name} {target_user.last_name if target_user.last_name else ''}"
        except:
            target_name = f"ID: {user_id}"
        
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
                
                ban_count = update_admin_action_count(chat_id, admin.id, "ban")
                
                log_text = f"🚫 **KULLANICI BANLANDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Yöneticinin Ban Sayısı:** {ban_count}\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("ban", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} başarıyla banlandı"
                
                add_banned_user(chat_id, user_id, reason, admin.id, target_name)
                
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
                
                log_text = f"✅ **KULLANICI BANI KALDIRILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("ban", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} banı kaldırıldı"
                
                remove_banned_user(chat_id, user_id)
                
            except Exception as e:
                notification = f"❌ Ban kaldırma işlemi sırasında hata: {str(e)}"
                
        elif action == "mute":
            try:
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
                
                mute_count = update_admin_action_count(chat_id, admin.id, "mute")
                
                log_text = f"🔇 **KULLANICI SUSTURULDU**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Yöneticinin Mute Sayısı:** {mute_count}\n" \
                          f"**Süre:** 1 saat\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("mute", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} 1 saat susturuldu"
                
                add_muted_user(chat_id, user_id, reason, admin.id, target_name, until_date)
                
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
                
                log_text = f"🔊 **KULLANICI SUSTURMASI KALDIRILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("mute", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} susturması kaldırıldı"
                
                remove_muted_user(chat_id, user_id)
                
            except Exception as e:
                notification = f"❌ Unmute işlemi sırasında hata: {str(e)}"
                
        elif action == "kick":
            try:
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
                
                kick_count = update_admin_action_count(chat_id, admin.id, "kick")
                
                log_text = f"👢 **KULLANICI ATILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Yöneticinin Kick Sayısı:** {kick_count}\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("kicks", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} gruptan atıldı"
                
            except Exception as e:
                notification = f"❌ Kick işlemi sırasında hata: {str(e)}"
                
        elif action == "warn":
            try:
                add_user_warning(chat_id, user_id, reason, admin.id)
                warnings = get_user_warnings(chat_id, user_id)
                warn_count = len(warnings)
                
                ensure_group_in_db(chat_id)
                settings = get_group_settings(chat_id)
                max_warns = settings['warn_max']
                warn_action = settings['warn_action']
                
                log_text = f"⚠️ **KULLANICI UYARILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("warns", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} uyarıldı. Uyarı sayısı: {warn_count}/{max_warns}"
                
                # Maksimum uyarı sayısına ulaşıldıysa ceza uygula
                if warn_count >= max_warns:
                    if warn_action == 'ban':
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
                                  f"**Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        await log_to_thread("ban", log_text, None, chat.id)
                        
                    elif warn_action == 'mute':
                        mute_duration = settings['warn_mute_duration']
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
                                  f"**Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        
                        await log_to_thread("mute", log_text, None, chat.id)
                    
                    # Uyarı sayısını sıfırla
                    clear_user_warnings(chat_id, user_id)
                
            except Exception as e:
                notification = f"❌ Warn işlemi sırasında hata: {str(e)}"
                
        elif action == "unwarn":
            try:
                warnings = get_user_warnings(chat_id, user_id)
                if not warnings:
                    notification = "⚠️ Bu kullanıcının hiç uyarısı yok."
                    await event.edit(notification)
                    return
                
                remove_user_warning(chat_id, user_id)
                
                remaining_warnings = get_user_warnings(chat_id, user_id)
                warn_count = len(remaining_warnings)
                
                ensure_group_in_db(chat_id)
                settings = get_group_settings(chat_id)
                max_warns = settings['warn_max']
                
                log_text = f"⚠️ **KULLANICI UYARISI KALDIRILDI**\n\n" \
                          f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                          f"**Kullanıcı:** {target_name} (`{user_id}`)\n" \
                          f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                          f"**Sebep:** {reason}\n" \
                          f"**Kalan Uyarı Sayısı:** {warn_count}/{max_warns}\n" \
                          f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await log_to_thread("warns", log_text, None, chat.id)
                notification = f"✅ Kullanıcı {target_name} bir uyarısı kaldırıldı. Kalan uyarı sayısı: {warn_count}/{max_warns}"
                
            except Exception as e:
                notification = f"❌ Unwarn işlemi sırasında hata: {str(e)}"
        
        await event.edit(notification)
        
        # Kullanıcı bilgilerini güncellenmiş şekilde gösterme
        if not event.is_private:
            await asyncio.sleep(1)
            info_command_text = f"/info {user_id}"
            await client.send_message(event.chat_id, info_command_text)
        
    except Exception as e:
        logger.error(f"Direkt işlem butonunda hata: {str(e)}")
        await event.answer(f"İşlem sırasında bir hata oluştu: {str(e)}", alert=True)

# Mesaj izleme ve flood kontrolü
@client.on(events.NewMessage)
async def track_messages(event):
    if not event.is_private and event.message:
        chat_id = event.chat_id
        user_id = event.sender_id
        
        # Günlük istatistikleri artır
        increment_stat("messages", chat_id)
        
        # Kullanıcı istatistiklerini güncelle
        update_user_stats(chat_id, user_id)
        
        # Flood kontrolü yap
        await check_flood(event)

# Anti-flood kontrolü
async def check_flood(event):
    if event.is_private:
        return False
    
    chat_id = event.chat_id
    user_id = event.sender_id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    # Flood ayarlarını al
    flood_settings = json.loads(settings['flood_settings'] or '{}')
    if not flood_settings:
        flood_settings = DEFAULT_FLOOD_CONFIG
    
    if not flood_settings.get("enabled", False):
        return False
    
    # Adminleri hariç tut
    if flood_settings.get("exclude_admins", True):
        try:
            participant = await client(GetParticipantRequest(event.chat, user_id))
            if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                return False
        except:
            pass
    
    current_time = datetime.now()
    flood_data[chat_id][user_id].append(current_time)
    
    # Eski mesajları temizle
    time_threshold = current_time - timedelta(seconds=flood_settings.get("seconds", 5))
    flood_data[chat_id][user_id] = [t for t in flood_data[chat_id][user_id] if t > time_threshold]
    
    # Flood kontrolü
    if len(flood_data[chat_id][user_id]) > flood_settings.get("messages", 5):
        action = flood_settings.get("action", "mute")
        
        try:
            flooder = await client.get_entity(user_id)
            flooder_name = f"{flooder.first_name} {flooder.last_name if flooder.last_name else ''}"
            
            chat = await client.get_entity(chat_id)
            
            log_text = f"⚠️ **FLOOD ALGILANDI**\n\n" \
                       f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                       f"**Kullanıcı:** {flooder_name} (`{user_id}`)\n" \
                       f"**Mesaj Sayısı:** {len(flood_data[chat_id][user_id])}\n" \
                       f"**Zaman Aralığı:** {flood_settings.get('seconds', 5)} saniye\n" \
                       f"**Uygulanan İşlem:** {action.upper()}\n" \
                       f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            if flood_settings.get("warn_only", False):
                await event.respond(f"⚠️ {flooder_name} Lütfen flood yapmayın!")
                if flood_settings.get("log_to_channel", True):
                    await log_to_thread("flood_warn", log_text, None, chat_id)
                return True
            
            appeal_button = Button.url("İtiraz Et", "https://t.me/arayis_itiraz")
            
            if action.lower() == "mute":
                mute_time = flood_settings.get("mute_time", 5)
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
                
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı {mute_time} dakika susturuldu.",
                    buttons=[[appeal_button]]
                )
                
            elif action.lower() == "kick":
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
                
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı gruptan atıldı.",
                    buttons=[[appeal_button]]
                )
                
            elif action.lower() == "ban":
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
                
                await event.respond(
                    f"⚠️ Kullanıcı {flooder_name} flood yapmaktan dolayı banlandı.",
                    buttons=[[appeal_button]]
                )
                
            elif action.lower() == "warn":
                add_user_warning(chat_id, user_id, "Flood yapmak", "Bot")
                
            elif action.lower() == "delete":
                await event.delete()
            
            if flood_settings.get("log_to_channel", True):
                await log_to_thread(f"flood_{action}", log_text, None, chat_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Anti-flood işlemi sırasında hata: {str(e)}")
            return False
    
    return False

# Admin kontrolü için yardımcı fonksiyon
async def is_admin(chat, user_id):
    try:
        participant = await client(GetParticipantRequest(channel=chat, participant=user_id))
        return isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator))
    except:
        return False

# Mesaj filtreleme (yasaklı kelimeler ve bağlantılar)
@client.on(events.NewMessage)
async def filter_messages(event):
    if event.is_private:
        return
    
    try:
        chat = await event.get_chat()
        sender = await event.get_sender()
        chat_id = chat.id
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        # Yöneticileri kontrol etme
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
        if not is_admin:
            forbidden_words = json.loads(settings['forbidden_words'] or '[]')
            for word in forbidden_words:
                if word.lower() in text.lower():
                    try:
                        await event.delete()
                        
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
        
        # Bağlantı kontrolü
        if not is_admin:
            has_link = False
            link_type = None
            link_value = None
            
            if re.search(r'(https?://\S+|www\.\S+)', text):
                has_link = True
                link_type = "URL"
                link_value = re.findall(r'(https?://\S+|www\.\S+)', text)
            elif re.search(r't\.me/[\w\+]+', text):
                has_link = True
                link_type = "Telegram"
                link_value = re.findall(r't\.me/[\w\+]+', text)
            elif message.entities:
                for entity in message.entities:
                    if isinstance(entity, (MessageEntityUrl, MessageEntityTextUrl)):
                        has_link = True
                        link_type = "Entity URL"
                        break
            
            if has_link:
                try:
                    await event.delete()
                    
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

# YASAKLI KELİME VE BAĞLANTI FİLTRELEME

# Yasaklı kelime ayarları
@client.on(events.NewMessage(pattercklist'))
async def forbidden_words_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    forbidden_words = json.loads(settings['forbidden_words'] or '[]')
    
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
        action = event.pattern_match.group(1).decode()
        chat_id = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        await event.answer()
        
        if action == "add":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Eklemek istediğiniz yasaklı kelimeyi girin:")
                word_response = await conv.get_response()
                word = word_response.text.lower()
                
                if word:
                    settings = get_group_settings(chat_id)
                    forbidden_words = json.loads(settings['forbidden_words'] or '[]')
                    
                    if word not in forbidden_words:
                        forbidden_words.append(word)
                        update_group_setting(chat_id, 'forbidden_words', forbidden_words)
                        await conv.send_message(f"'{word}' yasaklı kelimeler listesine eklendi.")
                    else:
                        await conv.send_message("Bu kelime zaten listede.")
                else:
                    await conv.send_message("Geçersiz kelime.")
        
        elif action == "list":
            settings = get_group_settings(chat_id)
            forbidden_words = json.loads(settings['forbidden_words'] or '[]')
            
            if forbidden_words:
                word_list = "\n".join([f"- {word}" for word in forbidden_words])
                await event.edit(f"📋 **Yasaklı Kelimeler Listesi**\n\n{word_list}")
            else:
                await event.edit("Yasaklı kelimeler listesi boş.")
        
        elif action == "clear":
            update_group_setting(chat_id, 'forbidden_words', [])
            await event.edit("Yasaklı kelimeler listesi temizlendi.")
            
    except Exception as e:
        logger.error(f"Yasaklı kelime buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# HOŞGELDİN MESAJLARI

# Hoşgeldin mesajı ayarları
@client.on(events.NewMessage(pattern=r'/welcome'))
async def welcome_message_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    status = "Açık ✅" if settings['welcome_enabled'] else "Kapalı ❌"
    
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if settings['welcome_enabled'] else 'Aç 🟢'}", 
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
    
    welcome_text = settings['welcome_text']
    welcome_buttons = json.loads(settings['welcome_buttons'] or '[]')
    
    button_info = ""
    if welcome_buttons:
        button_info = "\n\n**Mevcut Butonlar:**\n"
        for btn in welcome_buttons:
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
        action = event.pattern_match.group(1).decode()
        chat_id = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        await event.answer()
        
        if action == "toggle":
            settings = get_group_settings(chat_id)
            new_status = not settings['welcome_enabled']
            update_group_setting(chat_id, 'welcome_enabled', 1 if new_status else 0)
            
            status = "açıldı ✅" if new_status else "kapatıldı ❌"
            await event.edit(f"Hoşgeldin mesajı {status}")
        
        elif action == "text":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Yeni hoşgeldin mesajını girin:")
                text_response = await conv.get_response()
                new_text = text_response.text
                
                if new_text:
                    update_group_setting(chat_id, 'welcome_text', new_text)
                    await conv.send_message("Hoşgeldin mesajı güncellendi.")
                else:
                    await conv.send_message("Geçersiz mesaj.")
        
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
                    settings = get_group_settings(chat_id)
                    welcome_buttons = json.loads(settings['welcome_buttons'] or '[]')
                    
                    welcome_buttons.append({
                        "text": button_text,
                        "url": button_url
                    })
                    
                    update_group_setting(chat_id, 'welcome_buttons', welcome_buttons)
                    await conv.send_message(f"Buton eklendi: {button_text} -> {button_url}")
                else:
                    await conv.send_message("Geçersiz buton bilgisi.")
        
        elif action == "clear_buttons":
            update_group_setting(chat_id, 'welcome_buttons', [])
            await event.edit("Tüm butonlar temizlendi.")
            
    except Exception as e:
        logger.error(f"Hoşgeldin mesajı buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Hoşgeldin mesajı gönderme
@client.on(events.ChatAction)
async def welcome_new_users(event):
    try:
        if not event.user_joined and not event.user_added:
            return
        
        chat = await event.get_chat()
        chat_id = chat.id
        user = await event.get_user()
        
        # Giriş olayını logla
        log_text = f"👋 **YENİ ÜYE KATILDI**\n\n" \
                f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                f"**Kullanıcı:** {user.first_name} (`{user.id}`)\n" \
                f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("join_leave", log_text, None, chat.id)
        
        # İstatistikleri güncelle
        increment_stat("new_members", chat_id)
        
        # Hoşgeldin mesajı etkinse gönder
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        if settings['welcome_enabled']:
            welcome_text = settings['welcome_text']
            welcome_buttons = json.loads(settings['welcome_buttons'] or '[]')
            
            welcome_text = welcome_text.replace(
                "{user}", f"[{user.first_name}](tg://user?id={user.id})"
            ).replace(
                "{username}", f"@{user.username}" if user.username else user.first_name
            )
            
            buttons = None
            if welcome_buttons:
                buttons = []
                row = []
                for i, btn in enumerate(welcome_buttons):
                    row.append(Button.url(btn["text"], btn["url"]))
                    
                    if (i + 1) % 2 == 0 or i == len(welcome_buttons) - 1:
                        buttons.append(row)
                        row = []
            
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

# Çıkış olaylarını loglama
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
        
        # İstatistikleri güncelle
        increment_stat("left_members", event.chat_id)
        
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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    status = "Aktif ✅" if settings['repeated_enabled'] else "Devre Dışı ❌"
    
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if settings['repeated_enabled'] else 'Aç 🟢'}", 
        data=f"repeated_toggle_{chat.id}"
    )
    add_message_button = Button.inline("✏️ Mesaj Ekle", data=f"repeated_add_message_{chat.id}")
    list_messages_button = Button.inline("📋 Mesajları Listele/Düzenle", data=f"repeated_list_messages_{chat.id}")
    clear_messages_button = Button.inline("🗑️ Tüm Mesajları Temizle", data=f"repeated_clear_messages_{chat.id}")
    
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
    
    repeated_messages = json.loads(settings['repeated_messages'] or '[]')
    repeated_buttons = json.loads(settings['repeated_buttons'] or '[]')
    
    msg_count = len(repeated_messages)
    button_count = len(repeated_buttons)
    
    default_interval = settings['repeated_interval']
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
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        default_interval = settings['repeated_interval']
        if default_interval < 60:
            default_interval_text = f"{default_interval} saniye"
        elif default_interval < 3600:
            default_interval_text = f"{default_interval // 60} dakika"
        else:
            default_interval_text = f"{default_interval // 3600} saat"
        
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
        
        ensure_group_in_db(chat_id)
        
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
                
                update_group_setting(chat_id, 'repeated_interval', seconds)
                
                if seconds < 60:
                    interval_text = f"{seconds} saniye"
                elif seconds < 3600:
                    interval_text = f"{seconds // 60} dakika"
                else:
                    interval_text = f"{seconds // 3600} saat"
                
                await conv.send_message(f"Varsayılan tekrarlama süresi {interval_text} olarak ayarlandı.")
            else:
                await conv.send_message("Geçersiz format. Değişiklik yapılmadı.")
        
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
        
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Ana menüye dönüş işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tekrarlanan mesajları toggle etme
@client.on(events.CallbackQuery(pattern=r'repeated_toggle_(-?\d+)'))
async def repeated_toggle_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        new_status = not settings['repeated_enabled']
        update_group_setting(chat_id, 'repeated_enabled', 1 if new_status else 0)
        
        status = "aktif" if new_status else "devre dışı"
        await event.answer(f"Tekrarlanan mesajlar {status} olarak ayarlandı.")
        
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
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
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
            default_interval = settings['repeated_interval']
            
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
            
            repeated_messages = json.loads(settings['repeated_messages'] or '[]')
            repeated_messages.append(new_message)
            update_group_setting(chat_id, 'repeated_messages', repeated_messages)
            
            # Mesajın bilgilerini göster
            interval_text = format_interval(interval)
            
            await conv.send_message(
                f"Mesaj eklendi!\n\n"
                f"**Mesaj:** {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n"
                f"**Süre:** {interval_text}"
            )
            
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
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        messages = json.loads(settings['repeated_messages'] or '[]')
        
        if not messages:
            await event.answer("Henüz tekrarlanan mesaj eklenmemiş.", alert=True)
            return
        
        await event.answer()
        
        # Mesaj listesi ve düzenleme butonları
        message_buttons = []
        
        for i, message in enumerate(messages):
            # Mesajı kısaltıp göster
            if isinstance(message, str):
                message_text = message
                interval = settings['repeated_interval']
            else:
                message_text = message.get("text", "")
                interval = message.get("interval", settings['repeated_interval'])
                
            if len(message_text) > 30:
                message_preview = message_text[:27] + "..."
            else:
                message_preview = message_text
                
            interval_text = format_interval(interval)
            
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

# Tüm mesajları temizle
@client.on(events.CallbackQuery(pattern=r'repeated_clear_messages_(-?\d+)'))
async def repeated_clear_messages_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        messages = json.loads(settings['repeated_messages'] or '[]')
        
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
        
        update_group_setting(chat_id, 'repeated_messages', [])
        
        await event.answer("Tüm tekrarlanan mesajlar silindi.")
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Mesajları temizleme onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Buton ekleme
@client.on(events.CallbackQuery(pattern=r'repeated_add_button_(-?\d+)'))
async def repeated_add_button_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
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
            repeated_buttons = json.loads(settings['repeated_buttons'] or '[]')
            repeated_buttons.append({
                "text": button_text,
                "url": button_url
            })
            
            update_group_setting(chat_id, 'repeated_buttons', repeated_buttons)
            
            await conv.send_message(f"Buton eklendi:\n**Metin:** {button_text}\n**URL:** {button_url}")
    
    except Exception as e:
        logger.error(f"Buton ekleme işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Butonları temizleme
@client.on(events.CallbackQuery(pattern=r'repeated_clear_buttons_(-?\d+)'))
async def repeated_clear_buttons_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        buttons = json.loads(settings['repeated_buttons'] or '[]')
        
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
        
        update_group_setting(chat_id, 'repeated_buttons', [])
        
        await event.answer("Tüm butonlar silindi.")
        await repeated_messages_menu(event)
        
    except Exception as e:
        logger.error(f"Butonları temizleme onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Tekrarlanan mesajları gönderme işlevi
async def send_repeated_messages():
    while True:
        try:
            current_time = time.time()
            
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT chat_id, repeated_messages, repeated_buttons, repeated_interval 
                FROM groups 
                WHERE repeated_enabled = 1
            ''')
            
            for row in cursor.fetchall():
                chat_id_str, messages_json, buttons_json, interval = row
                chat_id = int(chat_id_str)
                
                messages = json.loads(messages_json or '[]')
                buttons = json.loads(buttons_json or '[]')
                
                for i, message_data in enumerate(messages):
                    if isinstance(message_data, str):
                        # Eski format mesajları yeni formata dönüştür
                        message_text = message_data
                        message_interval = interval
                        last_sent = 0
                    else:
                        message_text = message_data.get("text", "")
                        message_interval = message_data.get("interval", interval)
                        last_sent = message_data.get("last_sent", 0)
                    
                    if current_time - last_sent >= message_interval:
                        try:
                            message_buttons = None
                            if buttons:
                                btn_array = []
                                row = []
                                for j, btn in enumerate(buttons):
                                    row.append(Button.url(btn["text"], btn["url"]))
                                    
                                    if (j + 1) % 2 == 0 or j == len(buttons) - 1:
                                        btn_array.append(row)
                                        row = []
                                
                                if btn_array:
                                    message_buttons = btn_array
                            
                            await client.send_message(
                                chat_id,
                                message_text,
                                buttons=message_buttons
                            )
                            
                            # Son gönderim zamanını güncelle
                            if isinstance(message_data, dict):
                                message_data["last_sent"] = current_time
                                messages[i] = message_data
                                
                                cursor.execute(
                                    'UPDATE groups SET repeated_messages = ? WHERE chat_id = ?',
                                    (json.dumps(messages, ensure_ascii=False), chat_id_str)
                                )
                            
                            log_text = f"🔄 **TEKRARLANAN MESAJ GÖNDERİLDİ**\n\n" \
                                    f"**Grup ID:** `{chat_id}`\n" \
                                    f"**Mesaj:** {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n" \
                                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            
                            await log_to_thread("repeated_msgs", log_text, None, chat_id)
                            
                        except Exception as e:
                            logger.error(f"Tekrarlanan mesaj gönderilirken hata oluştu: {e}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Tekrarlanan mesaj döngüsünde hata oluştu: {e}")
        
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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    
    # Yetki zaten var mı kontrol et
    permissions = get_admin_permissions(chat_id, user_id)
    if permission_type not in permissions:
        add_admin_permission(chat_id, user_id, permission_type)
        
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
            
            log_text = f"👮 **YETKİ VERİLDİ**\n\n" \
                    f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                    f"**Veren Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                    f"**Yetki:** {permission_names[permission_type]}\n" \
                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await log_to_thread("join_leave", log_text, None, chat.id)
            
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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    
    permissions = get_admin_permissions(chat_id, user_id)
    if permission_type in permissions:
        remove_admin_permission(chat_id, user_id, permission_type)
        
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
            
            log_text = f"👮 **YETKİ ALINDI**\n\n" \
                    f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                    f"**Kullanıcı:** {user.first_name} (`{user_id}`)\n" \
                    f"**Alan Yönetici:** {event.sender.first_name} (`{event.sender_id}`)\n" \
                    f"**Yetki:** {permission_names[permission_type]}\n" \
                    f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await log_to_thread("join_leave", log_text, None, chat.id)
            
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
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    # Menü butonları
    set_max_button = Button.inline("🔢 Maksimum Uyarı", data=f"warn_max_{chat.id}")
    set_action_button = Button.inline(
        f"🔄 Eylem: {'Ban' if settings['warn_action'] == 'ban' else 'Mute'}", 
        data=f"warn_action_{chat.id}"
    )
    set_duration_button = Button.inline("⏱️ Mute Süresi", data=f"warn_duration_{chat.id}")
    
    buttons = [
        [set_max_button],
        [set_action_button],
        [set_duration_button]
    ]
    
    action_text = "Ban" if settings['warn_action'] == "ban" else f"Mute ({settings['warn_mute_duration']} saat)"
    
    await event.respond(
        f"⚠️ **Uyarı Ayarları**\n\n"
        f"**Maksimum Uyarı:** {settings['warn_max']}\n"
        f"**Eylem:** {action_text}",
        buttons=buttons
    )

# Uyarı ayarları menü işleyicileri
@client.on(events.CallbackQuery(pattern=r'warn_(max|action|duration)_(-?\d+)'))
async def warn_settings_handler(event):
    try:
        action = event.pattern_match.group(1).decode()
        chat_id = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        await event.answer()
        
        if action == "max":
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Maksimum uyarı sayısını girin (1-10):")
                max_response = await conv.get_response()
                
                try:
                    max_warns = int(max_response.text)
                    if 1 <= max_warns <= 10:
                        update_group_setting(chat_id, 'warn_max', max_warns)
                        await conv.send_message(f"Maksimum uyarı sayısı {max_warns} olarak ayarlandı.")
                    else:
                        await conv.send_message("Geçersiz değer. 1 ile 10 arasında bir sayı girin.")
                except ValueError:
                    await conv.send_message("Geçersiz değer. Lütfen bir sayı girin.")
        
        elif action == "action":
            settings = get_group_settings(chat_id)
            current_action = settings['warn_action']
            new_action = "mute" if current_action == "ban" else "ban"
            
            update_group_setting(chat_id, 'warn_action', new_action)
            
            action_text = "Ban" if new_action == "ban" else "Mute"
            await event.edit(f"Uyarı eylem türü '{action_text}' olarak değiştirildi.")
        
        elif action == "duration":
            settings = get_group_settings(chat_id)
            if settings['warn_action'] != "mute":
                await event.edit("Bu ayar sadece eylem türü 'Mute' olduğunda geçerlidir.")
                return
            
            async with client.conversation(event.sender_id, timeout=300) as conv:
                await event.delete()
                await conv.send_message("Mute süresini saat cinsinden girin (1-168):")
                duration_response = await conv.get_response()
                
                try:
                    duration = int(duration_response.text)
                    if 1 <= duration <= 168:
                        update_group_setting(chat_id, 'warn_mute_duration', duration)
                        await conv.send_message(f"Mute süresi {duration} saat olarak ayarlandı.")
                    else:
                        await conv.send_message("Geçersiz değer. 1 ile 168 (1 hafta) arasında bir sayı girin.")
                except ValueError:
                    await conv.send_message("Geçersiz değer. Lütfen bir sayı girin.")
                    
    except Exception as e:
        logger.error(f"Uyarı ayarları buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# İstatistik raporu oluşturma
# İstatistik raporu oluşturma (düzeltilmiş)
async def generate_stats_report(chat_id):
    chat_id_str = str(chat_id)
    
    try:
        # Chat entity'sini al ve tip kontrolü yap
        chat_entity = await client.get_entity(int(chat_id))
        
        # Eğer User objesi geldiyse private chat'tir, grup değil
        if hasattr(chat_entity, 'first_name'):
            # Bu bir kullanıcı, grup değil
            return f"Bu bir kullanıcı profili, grup istatistikleri alınamaz.", "Kullanıcı Profili"
        
        # Grup/kanal olduğunu doğrula
        if not hasattr(chat_entity, 'title'):
            return f"Chat title alınamadı (ID: {chat_id})", "Bilinmeyen Chat"
        
        chat_title = chat_entity.title
        
        # Üye sayısını al
        try:
            if hasattr(chat_entity, 'participants_count'):
                member_count = chat_entity.participants_count
            else:
                # Tam chat bilgisini al
                full_chat = await client(GetFullChannelRequest(chat_entity))
                member_count = full_chat.full_chat.participants_count
        except Exception as member_error:
            logger.warning(f"Üye sayısı alınamadı: {member_error}")
            member_count = "Bilinmiyor"
        
        # Günlük istatistikleri al
        stats = get_daily_stats(chat_id)
        new_members = stats.get("new_members", 0)
        left_members = stats.get("left_members", 0)
        messages = stats.get("messages", 0)
        
        net_change = new_members - left_members
        change_emoji = "📈" if net_change > 0 else "📉" if net_change < 0 else "➖"
        
        report = f"📊 **GÜNLÜK İSTATİSTİK RAPORU**\n\n"
        report += f"**Grup:** {chat_title} (`{chat_id}`)\n"
        report += f"**Tarih:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
        
        report += f"**Üye Sayısı:** {member_count}\n"
        report += f"**Üye Değişimi:** {change_emoji} {net_change:+d}\n"
        report += f"➖ Yeni Üyeler: {new_members}\n"
        report += f"➖ Ayrılan Üyeler: {left_members}\n\n"
        
        report += f"**Aktivite:**\n"
        report += f"💬 Mesaj Sayısı: {messages}\n"
        
        return report, chat_title
    
    except Exception as e:
        logger.error(f"İstatistik raporu oluşturulurken hata: {e}")
        return f"İstatistik raporu oluşturulurken hata oluştu: {str(e)}", "Hata"

# Günlük istatistik raporunu gönder
async def send_daily_report():
    while True:
        try:
            turkey_tz = pytz.timezone('Europe/Istanbul')
            now = datetime.now(turkey_tz)
            
            target_time = now.replace(hour=21, minute=0, second=0, microsecond=0)
            
            if now.time() >= target_time.time():
                target_time = target_time + timedelta(days=1)
            
            wait_seconds = (target_time - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Tüm aktif gruplar için rapor oluştur
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT chat_id FROM groups')
            group_ids = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            all_reports = ""
            for chat_id_str in group_ids:
                try:
                    chat_id = int(chat_id_str)
                    report, chat_title = await generate_stats_report(chat_id)
                    all_reports += f"{report}\n{'─' * 30}\n\n"
                except Exception as e:
                    logger.error(f"İstatistik raporu oluşturulurken hata ({chat_id_str}): {e}")
            
            if all_reports:
                header = f"📊 **TÜM GRUPLARIN GÜNLÜK İSTATİSTİK RAPORU**\n" \
                        f"**Tarih:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
                
                await log_to_thread("stats", header + all_reports, None, None)
            
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Günlük rapor göndericisinde hata: {e}")
            await asyncio.sleep(60)

# Stat komutu
@client.on(events.NewMessage(pattern=r'/stat(?:@\w+)?'))
async def stat_command(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat_id = event.chat_id
    report, _ = await generate_stats_report(chat_id)
    await event.respond(report)

# Anti-flood ayarları komutu
@client.on(events.NewMessage(pattern=r'/setflood(?:@\w+)?(?:\s+(.+))?'))
async def set_flood_command(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    args = event.pattern_match.group(1)
    
    if not args:
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
    
    chat_id = event.chat_id
    ensure_group_in_db(chat_id)
    
    parts = args.strip().split()
    if len(parts) < 2:
        await event.respond("Hata: Yeterli argüman sağlanmadı. Kullanım: `/setflood AYAR DEĞER`")
        return
    
    setting = parts[0].lower()
    value = parts[1].lower()
    
    settings = get_group_settings(chat_id)
    flood_settings = json.loads(settings['flood_settings'] or '{}')
    if not flood_settings:
        flood_settings = DEFAULT_FLOOD_CONFIG.copy()
    
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
        update_group_setting(chat_id, 'flood_settings', flood_settings)
        
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

# Log ayarları komutu
@client.on(events.NewMessage(pattern=r'/log'))
async def log_settings_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat = await event.get_chat()
    chat_id = chat.id
    
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    status = "Aktif ✅" if settings['log_enabled'] else "Devre Dışı ❌"
    log_channel = settings['log_channel_id']
    
    toggle_button = Button.inline(
        f"{'Kapat 🔴' if settings['log_enabled'] else 'Aç 🟢'}", 
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

# İtiraz buton işleyicisi
@client.on(events.CallbackQuery(pattern=r'appeal_(ban|mute|kick|warn)_(\d+)'))
async def appeal_button_handler(event):
    try:
        action = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        
        await event.answer()
        
        try:
            original_message = await event.get_message()
            new_text = original_message.text + "\n\n⚠️ İtiraz sistemi: @arayis_itiraz"
            new_buttons = [Button.url("🔍 @arayis_itiraz", "https://t.me/arayis_itiraz")]
            
            await original_message.edit(
                text=new_text,
                buttons=new_buttons
            )
        except Exception as e:
            logger.error(f"Mesaj düzenleme hatası: {e}")
        
        try:
            await client.send_message(
                user_id,
                f"İtiraz için doğrudan @arayis_itiraz ile iletişime geçebilirsiniz:",
                buttons=[Button.url("@arayis_itiraz", "https://t.me/arayis_itiraz")]
            )
        except Exception as e:
            logger.error(f"DM üzerinden buton gönderilirken hata: {e}")
            pass
            
    except Exception as e:
        logger.error(f"İtiraz buton işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Toplu üye işlemleri
@client.on(events.NewMessage(pattern=r'/setmember'))
async def setmember_menu(event):
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    if event.is_private:
        await event.respond("Bu komut sadece gruplarda kullanılabilir.")
        return
    
    chat = await event.get_chat()
    
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

# Tüm banları kaldırma onayı
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

# Tüm banları kaldırma onayı
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
            unbanned_count = 0
            failed_count = 0
            
            # Veritabanından banlı kullanıcıları al
            banned_users = get_all_banned_users(chat_id)
            
            for user_id_str in banned_users:
                user_id = int(user_id_str)
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
                    
                    unbanned_count += 1
                    
                except Exception as e:
                    logger.error(f"Kullanıcı {user_id} banı kaldırılırken hata: {str(e)}")
                    failed_count += 1
            
            # Veritabanından tüm ban kayıtlarını temizle
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM banned_users WHERE chat_id = ?', (str(chat_id),))
            conn.commit()
            conn.close()
            
            if unbanned_count > 0:
                result_text = f"✅ **İŞLEM TAMAMLANDI**\n\n" \
                             f"**Grup:** {chat.title}\n" \
                             f"**İşlem:** Toplu ban kaldırma\n" \
                             f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                             f"**Başarılı:** {unbanned_count} kullanıcı\n"
                
                if failed_count > 0:
                    result_text += f"**Başarısız:** {failed_count} kullanıcı\n"
                
                result_text += f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await event.edit(result_text)
                await log_to_thread("ban", result_text, None, chat_id)
            else:
                await event.edit("ℹ️ Banlı kullanıcı bulunamadı veya tüm işlemler başarısız oldu.")
        
        except Exception as e:
            logger.error(f"Tüm banları kaldırma işleminde hata: {str(e)}")
            await event.edit(f"❌ İşlem sırasında bir hata oluştu: {str(e)}")
    
    except Exception as e:
        logger.error(f"Ban kaldırma onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# İptal butonu
@client.on(events.CallbackQuery(pattern=r'cancel_operation_(-?\d+)'))
async def cancel_operation_handler(event):
    try:
        await event.edit("❌ İşlem iptal edildi.")
    
    except Exception as e:
        logger.error(f"İptal işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Report komutu
@client.on(events.NewMessage(pattern=r'/report(?:@\w+)?(?:\s+(.+))?'))
async def report_command(event):
    if event.is_private:
        await event.respond("Bu komut sadece gruplarda kullanılabilir.")
        return
    
    try:
        chat = await event.get_chat()
        reporter = await event.get_sender()
        reason = event.pattern_match.group(1)
        reply_message = None
        
        if event.reply_to:
            try:
                reply_message = await event.get_reply_message()
            except Exception as e:
                logger.error(f"Yanıt verilen mesajı alırken hata: {str(e)}")
                reply_message = None
        
        if not reply_message and not reason:
            await event.respond("Lütfen bir sebep belirtin veya bir mesaja yanıt verin.\nÖrnek: `/report spam mesajlar atıyor`")
            return
        
        # Grup adminlerini al
        admin_list = []
        admin_mentions = []
        
        try:
            admins = []
            async for user in client.iter_participants(chat):
                try:
                    participant = await client(GetParticipantRequest(
                        chat.id,
                        user.id
                    ))
                    
                    if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                        if not user.bot:
                            admins.append(user)
                except Exception as e:
                    continue
            
            if not admins:
                admins.append(reporter)
            
            for admin in admins:
                admin_list.append(admin)
                admin_mentions.append(f"[{admin.first_name}](tg://user?id={admin.id})")
                
        except Exception as e:
            logger.error(f"Adminleri alırken hata: {str(e)}")
            admin_list.append(reporter)
            admin_mentions.append(f"[{reporter.first_name}](tg://user?id={reporter.id})")
        
        # Rapor mesajını hazırla
        reported_user_name = "Bilinmeyen Kullanıcı"
        reported_user_id = 0
        message_link = None
        message_text = "[Metin içeriği yok]"
        
        if reply_message:
            try:
                reported_user = await reply_message.get_sender()
                if reported_user:
                    reported_user_name = reported_user.first_name
                    reported_user_id = reported_user.id
                
                if hasattr(reply_message, 'id'):
                    chat_id_for_link = str(chat.id).replace('-100', '')
                    message_link = f"https://t.me/c/{chat_id_for_link}/{reply_message.id}"
                
                if hasattr(reply_message, 'text') and reply_message.text:
                    message_text = reply_message.text[:1000]
                    if len(reply_message.text) > 1000:
                        message_text += "...\n[Mesaj çok uzun, kısaltıldı]"
            except Exception as e:
                logger.error(f"Rapor edilecek mesaj bilgilerini alırken hata: {str(e)}")
        
        # DM raporu hazırla
        dm_report_text = f"📢 **YENİ RAPOR**\n\n" \
                        f"**Grup:** {chat.title}\n" \
                        f"**Rapor Eden:** [{reporter.first_name}](tg://user?id={reporter.id})\n"
                        
        if reply_message:
            dm_report_text += f"**Rapor Edilen:** [{reported_user_name}](tg://user?id={reported_user_id})\n"
                
        if reason:
            dm_report_text += f"**Sebep:** {reason}\n\n"
            
        if reply_message:
            dm_report_text += f"**Rapor Edilen Mesaj:**\n{message_text}"
            
            if hasattr(reply_message, 'media') and reply_message.media:
                dm_report_text += "\n[Mesajda medya içeriği bulunmaktadır]"
        
        # Adminlere DM gönder
        for admin in admin_list:
            try:
                if admin.id != reporter.id:
                    buttons = None
                    if message_link:
                        buttons = [Button.url("📝 Mesaja Git", message_link)]
                    
                    await client.send_message(
                        admin.id, 
                        dm_report_text, 
                        parse_mode='md',
                        buttons=buttons
                    )
            except Exception as e:
                logger.error(f"Admin {admin.id}'e DM gönderilirken hata: {str(e)}")
        
        # Grupta adminleri etiketle
        try:
            admin_tags = " ".join(admin_mentions)
            
            group_report = f"⚠️ **DİKKAT ADMİNLER** ⚠️\n\n" \
                        f"**Rapor Eden:** [{reporter.first_name}](tg://user?id={reporter.id})\n"
            
            if reply_message:
                group_report += f"**Rapor Edilen:** [{reported_user_name}](tg://user?id={reported_user_id})\n"
            
            if reason:
                group_report += f"**Sebep:** {reason}\n"
                
            group_report += f"\n{admin_tags}"
            
            report_msg = await event.respond(group_report, parse_mode='md')
            
            await asyncio.sleep(1)
            
            try:
                await report_msg.edit("✅ **Rapor adminlere bildirildi!**", parse_mode='md')
            except Exception as e:
                logger.error(f"Rapor mesajını düzenlerken hata: {str(e)}")
            
            try:
                await event.delete()
            except:
                pass
        except Exception as e:
            logger.error(f"Grup içinde adminleri etiketlerken hata: {str(e)}")
            await event.respond("Rapor adminlere bildirildi!")
            
    except Exception as e:
        logger.error(f"Rapor gönderme sırasında genel hata: {str(e)}")
        await event.respond("Rapor adminlere bildirildi!")
        
# EKSIK FONKSIYONLAR VE HANDLER'LAR

# User messages tracking global değişkeni
user_messages = {}

# Flood config ekleme fonksiyonu
def add_flood_config_to_group(chat_id):
    """Anti-flood config'i gruba ekle"""
    ensure_group_in_db(chat_id)
    settings = get_group_settings(chat_id)
    
    # Eğer flood ayarları yoksa varsayılan ayarları ekle
    if not settings['flood_settings'] or settings['flood_settings'] == '{}':
        update_group_setting(chat_id, 'flood_settings', DEFAULT_FLOOD_CONFIG)

# Yeni üyeleri takip et
@client.on(events.ChatAction)
async def track_new_members(event):
    try:
        if event.user_joined or event.user_added:
            chat_id = event.chat_id
            user = await event.get_user()
            
            # İstatistikleri güncelle
            increment_stat("new_members", chat_id)
            
            # User stats'a ekle
            update_user_stats(chat_id, user.id)
            
    except Exception as e:
        logger.error(f"Yeni üye takibinde hata: {str(e)}")

# Çıkan üyeleri takip et
@client.on(events.ChatAction)
async def track_left_members(event):
    try:
        if event.user_left or event.user_kicked:
            chat_id = event.chat_id
            
            # İstatistikleri güncelle
            increment_stat("left_members", chat_id)
            
    except Exception as e:
        logger.error(f"Çıkan üye takibinde hata: {str(e)}")

# İstatistikleri kaydet
def save_stats():
    """İstatistikleri kaydet - SQLite'da otomatik kaydediliyor"""
    pass

# İstatistikleri yükle  
def load_stats():
    """İstatistikleri yükle - SQLite'dan otomatik yükleniyor"""
    pass

# Günlük istatistikleri sıfırla
def reset_daily_stats():
    """Günlük istatistikleri sıfırla"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        cursor.execute('DELETE FROM daily_stats WHERE date < ?', (yesterday,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"İstatistik sıfırlama hatası: {str(e)}")

# Action button handler
@client.on(events.CallbackQuery(pattern=r'action_(approve|reject)_(\d+)_(.+)'))
async def action_button_handler(event):
    try:
        action = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        action_type = event.pattern_match.group(3).decode()
        
        chat = await event.get_chat()
        admin = await event.get_sender()
        
        if action == "approve":
            # Onaylandı - cezayı kaldır
            if action_type == "ban":
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
                remove_banned_user(chat.id, user_id)
                
            elif action_type == "mute":
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
                remove_muted_user(chat.id, user_id)
            
            await event.edit(f"✅ {action_type.upper()} onaylandı ve kaldırıldı.")
            
        else:  # reject
            await event.edit(f"❌ {action_type.upper()} itirazı reddedildi.")
        
        # Log kaydet
        log_text = f"⚖️ **İTİRAZ KARARI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı ID:** `{user_id}`\n" \
                  f"**İşlem:** {action_type.upper()}\n" \
                  f"**Karar:** {'ONAYLANDI' if action == 'approve' else 'REDDEDİLDİ'}\n" \
                  f"**Karar Veren:** {admin.first_name} (`{admin.id}`)\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("appeals", log_text, None, chat.id)
        
    except Exception as e:
        logger.error(f"Action button handler hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Appeal decision handler
@client.on(events.CallbackQuery(pattern=r'appeal_decision_(approve|reject)_(\d+)_(.+)'))
async def appeal_decision_handler(event):
    try:
        decision = event.pattern_match.group(1).decode()
        user_id = int(event.pattern_match.group(2).decode())
        punishment_type = event.pattern_match.group(3).decode()
        
        chat = await event.get_chat()
        admin = await event.get_sender()
        
        if decision == "approve":
            # İtiraz kabul edildi
            if punishment_type == "ban":
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
                remove_banned_user(chat.id, user_id)
                
            elif punishment_type == "mute":
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
                remove_muted_user(chat.id, user_id)
            
            await event.edit(f"✅ İtiraz kabul edildi. {punishment_type.upper()} kaldırıldı.")
            
            # Kullanıcıya bildir
            try:
                await client.send_message(
                    user_id,
                    f"✅ İtirazınız kabul edildi! {punishment_type.upper()} cezanız kaldırıldı."
                )
            except:
                pass
                
        else:  # reject
            await event.edit(f"❌ İtiraz reddedildi. {punishment_type.upper()} devam ediyor.")
            
            # Kullanıcıya bildir
            try:
                await client.send_message(
                    user_id,
                    f"❌ İtirazınız reddedildi. {punishment_type.upper()} cezanız devam ediyor."
                )
            except:
                pass
        
        # Log kaydet
        log_text = f"⚖️ **İTİRAZ KARARI**\n\n" \
                  f"**Grup:** {chat.title} (`{chat.id}`)\n" \
                  f"**Kullanıcı ID:** `{user_id}`\n" \
                  f"**Ceza Türü:** {punishment_type.upper()}\n" \
                  f"**Karar:** {'KABUL EDİLDİ' if decision == 'approve' else 'REDDEDİLDİ'}\n" \
                  f"**Karar Veren:** {admin.first_name} (`{admin.id}`)\n" \
                  f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await log_to_thread("appeals", log_text, None, chat.id)
        
    except Exception as e:
        logger.error(f"Appeal decision handler hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Mesaj düzenleme handler'ı
@client.on(events.CallbackQuery(pattern=r'repeated_edit_message_(-?\d+)_(\d+)'))
async def repeated_edit_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        messages = json.loads(settings['repeated_messages'] or '[]')
        
        if message_index >= len(messages):
            await event.answer("Mesaj bulunamadı.", alert=True)
            return
        
        message = messages[message_index]
        if isinstance(message, str):
            message_text = message
            interval = settings['repeated_interval']
        else:
            message_text = message.get("text", "")
            interval = message.get("interval", settings['repeated_interval'])
        
        edit_text_button = Button.inline("✏️ Metni Düzenle", data=f"repeated_edit_text_{chat_id}_{message_index}")
        edit_interval_button = Button.inline("⏱️ Süreyi Düzenle", data=f"repeated_edit_interval_{chat_id}_{message_index}")
        delete_button = Button.inline("🗑️ Mesajı Sil", data=f"repeated_delete_message_{chat_id}_{message_index}")
        back_button = Button.inline("⬅️ Geri", data=f"repeated_list_messages_{chat_id}")
        
        buttons = [
            [edit_text_button],
            [edit_interval_button],
            [delete_button],
            [back_button]
        ]
        
        interval_text = format_interval(interval)
        
        preview = message_text[:200] + ("..." if len(message_text) > 200 else "")
        
        await event.edit(
            f"📝 **Mesaj Düzenleme**\n\n"
            f"**Mesaj {message_index + 1}:**\n{preview}\n\n"
            f"**Süre:** {interval_text}",
            buttons=buttons
        )
        
    except Exception as e:
        logger.error(f"Mesaj düzenleme handler hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Mesaj metni düzenleme
@client.on(events.CallbackQuery(pattern=r'repeated_edit_text_(-?\d+)_(\d+)'))
async def repeated_edit_text_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        messages = json.loads(settings['repeated_messages'] or '[]')
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message("Yeni mesaj metnini girin:")
            text_response = await conv.get_response()
            new_text = text_response.text
            
            if new_text:
                if isinstance(messages[message_index], str):
                    messages[message_index] = {
                        "text": new_text,
                        "interval": settings['repeated_interval'],
                        "last_sent": 0
                    }
                else:
                    messages[message_index]["text"] = new_text
                
                update_group_setting(chat_id, 'repeated_messages', messages)
                await conv.send_message("Mesaj metni güncellendi.")
            else:
                await conv.send_message("Geçersiz metin. Değişiklik yapılmadı.")
        
    except Exception as e:
        logger.error(f"Mesaj metni düzenleme hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Mesaj süre düzenleme
@client.on(events.CallbackQuery(pattern=r'repeated_edit_interval_(-?\d+)_(\d+)'))
async def repeated_edit_interval_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        messages = json.loads(settings['repeated_messages'] or '[]')
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message(
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
                
                if isinstance(messages[message_index], str):
                    messages[message_index] = {
                        "text": messages[message_index],
                        "interval": seconds,
                        "last_sent": 0
                    }
                else:
                    messages[message_index]["interval"] = seconds
                
                update_group_setting(chat_id, 'repeated_messages', messages)
                
                interval_text = format_interval(seconds)
                await conv.send_message(f"Tekrarlama süresi {interval_text} olarak güncellendi.")
            else:
                await conv.send_message("Geçersiz format. Değişiklik yapılmadı.")
        
    except Exception as e:
        logger.error(f"Mesaj süre düzenleme hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Mesaj silme
@client.on(events.CallbackQuery(pattern=r'repeated_delete_message_(-?\d+)_(\d+)'))
async def repeated_delete_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        # Onay iste
        confirm_button = Button.inline("✅ Evet, Sil", data=f"repeated_confirm_delete_message_{chat_id}_{message_index}")
        cancel_button = Button.inline("❌ İptal", data=f"repeated_edit_message_{chat_id}_{message_index}")
        
        buttons = [
            [confirm_button],
            [cancel_button]
        ]
        
        await event.edit(
            "⚠️ **UYARI**\n\n"
            "Bu mesajı silmek istediğinize emin misiniz?\n"
            "Bu işlem geri alınamaz!",
            buttons=buttons
        )
        
    except Exception as e:
        logger.error(f"Mesaj silme handler hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Mesaj silme onayı
@client.on(events.CallbackQuery(pattern=r'repeated_confirm_delete_message_(-?\d+)_(\d+)'))
async def repeated_confirm_delete_message_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        message_index = int(event.pattern_match.group(2).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        messages = json.loads(settings['repeated_messages'] or '[]')
        
        if message_index < len(messages):
            del messages[message_index]
            update_group_setting(chat_id, 'repeated_messages', messages)
        
        await event.answer("Mesaj silindi.")
        await repeated_list_messages_handler(event)
        
    except Exception as e:
        logger.error(f"Mesaj silme onayı hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Log toggle butonu (tam implementation)
@client.on(events.CallbackQuery(pattern=r'logs_toggle_(-?\d+)'))
async def logs_toggle_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        if not settings['log_channel_id'] and not settings['log_enabled']:
            await event.answer("Önce bir log kanalı ayarlamalısınız!", alert=True)
            return
            
        new_status = not settings['log_enabled']
        update_group_setting(chat_id, 'log_enabled', 1 if new_status else 0)
        
        status = "aktif" if new_status else "devre dışı"
        await event.answer(f"Log sistemi {status} olarak ayarlandı.")
        
        await log_settings_menu(event)
    
    except Exception as e:
        logger.error(f"Log toggle işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# Log kanal ayarlama
@client.on(events.CallbackQuery(pattern=r'logs_set_channel_(-?\d+)'))
async def logs_set_channel_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message(
                "Log kanalı ID'sini girin:\n"
                "Örnek: -1001234567890\n\n"
                "⚠️ Bot'un bu kanala mesaj gönderme yetkisi olması gerekir."
            )
            response = await conv.get_response()
            
            try:
                channel_id = int(response.text)
                
                # Test mesajı gönder
                test_message = await client.send_message(
                    channel_id,
                    "✅ Log kanalı test mesajı. Bot başarıyla bağlandı!"
                )
                
                update_group_setting(chat_id, 'log_channel_id', channel_id)
                update_group_setting(chat_id, 'log_enabled', 1)
                
                await conv.send_message(
                    f"✅ Log kanalı başarıyla ayarlandı!\n"
                    f"Kanal ID: {channel_id}"
                )
                
                # Test mesajını sil
                await test_message.delete()
                
            except ValueError:
                await conv.send_message("❌ Geçersiz ID formatı.")
            except Exception as e:
                await conv.send_message(f"❌ Hata: {str(e)}")
        
    except Exception as e:
        logger.error(f"Log kanal ayarlama hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Thread ID'leri ayarlama
@client.on(events.CallbackQuery(pattern=r'logs_set_threads_(-?\d+)'))
async def logs_set_threads_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        await event.answer()
        
        # Thread kategorileri için butonlar
        thread_buttons = []
        for thread_type in ["ban", "mute", "kick", "warns", "forbidden_words", "join_leave", "voice_chats", "stats", "appeals"]:
            button = Button.inline(f"🧵 {thread_type.replace('_', ' ').title()}", 
                                 data=f"logs_set_specific_thread_{chat_id}_{thread_type}")
            thread_buttons.append([button])
        
        back_button = Button.inline("⬅️ Geri", data=f"logs_back_to_main_{chat_id}")
        thread_buttons.append([back_button])
        
        await event.edit(
            "🧵 **Thread ID Ayarları**\n\n"
            "Hangi log türü için thread ID ayarlamak istiyorsunuz?",
            buttons=thread_buttons
        )
        
    except Exception as e:
        logger.error(f"Thread ayarlama hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Belirli thread ayarlama
@client.on(events.CallbackQuery(pattern=r'logs_set_specific_thread_(-?\d+)_(.+)'))
async def logs_set_specific_thread_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        thread_type = event.pattern_match.group(2).decode()
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        async with client.conversation(event.sender_id, timeout=300) as conv:
            await event.answer()
            await event.delete()
            
            await conv.send_message(
                f"'{thread_type.replace('_', ' ').title()}' kategorisi için thread ID'sini girin:\n"
                f"Örnek: 123\n\n"
                f"0 girerseniz thread kullanılmaz."
            )
            response = await conv.get_response()
            
            try:
                thread_id = int(response.text)
                
                thread_ids = json.loads(settings['log_thread_ids'] or '{}')
                thread_ids[thread_type] = thread_id
                
                update_group_setting(chat_id, 'log_thread_ids', thread_ids)
                
                if thread_id == 0:
                    await conv.send_message(f"✅ '{thread_type}' için thread kullanımı kapatıldı.")
                else:
                    await conv.send_message(f"✅ '{thread_type}' için thread ID {thread_id} olarak ayarlandı.")
                
            except ValueError:
                await conv.send_message("❌ Geçersiz ID formatı.")
        
    except Exception as e:
        logger.error(f"Belirli thread ayarlama hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Log ana menüye dönüş
@client.on(events.CallbackQuery(pattern=r'logs_back_to_main_(-?\d+)'))
async def logs_back_to_main_handler(event):
    try:
        await log_settings_menu(event)
    except Exception as e:
        logger.error(f"Log ana menü dönüş hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Log test
@client.on(events.CallbackQuery(pattern=r'logs_test_(-?\d+)'))
async def logs_test_handler(event):
    try:
        chat_id = int(event.pattern_match.group(1).decode())
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        ensure_group_in_db(chat_id)
        settings = get_group_settings(chat_id)
        
        if not settings['log_enabled']:
            await event.answer("Log sistemi kapalı. Önce açın.", alert=True)
            return
        
        admin = await event.get_sender()
        
        test_text = f"🧪 **LOG TEST MESAJI**\n\n" \
                   f"**Test Eden:** {admin.first_name} (`{admin.id}`)\n" \
                   f"**Grup ID:** `{chat_id}`\n" \
                   f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" \
                   f"✅ Log sistemi çalışıyor!"
        
        await log_to_thread("stats", test_text, None, chat_id)
        await event.answer("Test mesajı gönderildi!", alert=True)
        
    except Exception as e:
        logger.error(f"Log test hatası: {str(e)}")
        await event.answer("Test sırasında hata oluştu", alert=True)

# Tüm muteleri kaldırma
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

# Tüm muteleri kaldırma onayı
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
            unmuted_count = 0
            failed_count = 0
            
            # Veritabanından susturulmuş kullanıcıları al
            muted_users = get_all_muted_users(chat_id)
            
            for user_id_str in muted_users:
                user_id = int(user_id_str)
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
                    
                    unmuted_count += 1
                    
                except Exception as e:
                    logger.error(f"Kullanıcı {user_id} mute kaldırılırken hata: {str(e)}")
                    failed_count += 1
            
            # Veritabanından tüm mute kayıtlarını temizle
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM muted_users WHERE chat_id = ?', (str(chat_id),))
            conn.commit()
            conn.close()
            
            if unmuted_count > 0:
                result_text = f"✅ **İŞLEM TAMAMLANDI**\n\n" \
                             f"**Grup:** {chat.title}\n" \
                             f"**İşlem:** Toplu mute kaldırma\n" \
                             f"**Yönetici:** {admin.first_name} (`{admin.id}`)\n" \
                             f"**Başarılı:** {unmuted_count} kullanıcı\n"
                
                if failed_count > 0:
                    result_text += f"**Başarısız:** {failed_count} kullanıcı\n"
                
                result_text += f"**Zaman:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                
                await event.edit(result_text)
                await log_to_thread("mute", result_text, None, chat_id)
            else:
                await event.edit("ℹ️ Susturulmuş kullanıcı bulunamadı veya tüm işlemler başarısız oldu.")
        
        except Exception as e:
            logger.error(f"Tüm muteleri kaldırma işleminde hata: {str(e)}")
            await event.edit(f"❌ İşlem sırasında bir hata oluştu: {str(e)}")
    
    except Exception as e:
        logger.error(f"Mute kaldırma onayı işleyicisinde hata: {str(e)}")
        await event.answer("İşlem sırasında bir hata oluştu", alert=True)

# SON EKSİK KISIMLAR - Kodun sonuna ekleyin

# Flood check handler (tam implementasyon)
@client.on(events.CallbackQuery(pattern=r'flood_check_(.+)'))
async def flood_check_handler(event):
    try:
        action = event.pattern_match.group(1).decode()
        chat_id = event.chat_id
        
        if not await check_admin_permission(event, "edit_group"):
            await event.answer("Bu işlemi yapmak için yetkiniz yok.", alert=True)
            return
        
        if action == "enable":
            ensure_group_in_db(chat_id)
            settings = get_group_settings(chat_id)
            flood_settings = json.loads(settings['flood_settings'] or '{}')
            flood_settings["enabled"] = True
            update_group_setting(chat_id, 'flood_settings', flood_settings)
            await event.answer("Anti-flood etkinleştirildi.")
        
        elif action == "disable":
            ensure_group_in_db(chat_id)
            settings = get_group_settings(chat_id)
            flood_settings = json.loads(settings['flood_settings'] or '{}')
            flood_settings["enabled"] = False
            update_group_setting(chat_id, 'flood_settings', flood_settings)
            await event.answer("Anti-flood devre dışı bırakıldı.")
            
    except Exception as e:
        logger.error(f"Flood check handler hatası: {str(e)}")
        await event.answer("İşlem sırasında hata oluştu", alert=True)

# Global daily stats dictionary (orijinal kodunuzdaki gibi)
daily_stats = {
    "messages": defaultdict(int),
    "new_members": defaultdict(int),
    "left_members": defaultdict(int),
    "bans": defaultdict(int),
    "mutes": defaultdict(int),
    "kicks": defaultdict(int),
    "warns": defaultdict(int)
}

# İstatistik dosyası yolu
STATS_FILE = 'daily_stats.json'

# İstatistikleri kaydet (orijinal implementasyon)
def save_stats():
    """Günlük istatistikleri dosyaya kaydet"""
    try:
        stats_data = {}
        for stat_type, data in daily_stats.items():
            stats_data[stat_type] = dict(data)
        
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"İstatistik kaydetme hatası: {e}")

# İstatistikleri yükle (orijinal implementasyon)
def load_stats():
    """Günlük istatistikleri dosyadan yükle"""
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                stats_data = json.load(f)
            
            for stat_type, data in stats_data.items():
                if stat_type in daily_stats:
                    daily_stats[stat_type] = defaultdict(int, data)
    except Exception as e:
        logger.error(f"İstatistik yükleme hatası: {e}")

# Günlük istatistikleri sıfırla (genişletilmiş)
def reset_daily_stats():
    """Her gün istatistikleri sıfırla"""
    try:
        # Global dictionary'yi temizle
        for stat_type in daily_stats:
            daily_stats[stat_type].clear()
        
        # Veritabanındaki eski kayıtları temizle (7 günden eski)
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        cursor.execute('DELETE FROM daily_stats WHERE date < ?', (week_ago,))
        
        conn.commit()
        conn.close()
        
        # Dosyayı kaydet
        save_stats()
        
        logger.info("Günlük istatistikler sıfırlandı")
    except Exception as e:
        logger.error(f"İstatistik sıfırlama hatası: {e}")

# Periyodik istatistik sıfırlama görevi
async def daily_stats_reset_task():
    """Her gün gece yarısı istatistikleri sıfırla"""
    while True:
        try:
            now = datetime.now()
            # Bir sonraki gece yarısını hesapla
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_seconds = (midnight - now).total_seconds()
            
            await asyncio.sleep(sleep_seconds)
            reset_daily_stats()
            
        except Exception as e:
            logger.error(f"Günlük sıfırlama görevinde hata: {e}")
            await asyncio.sleep(3600)  # Hata durumunda 1 saat bekle

# Kullanıcı mesajlarını sayma (geliştirilmiş)
async def count_user_messages(chat_id, user_id):
    """Kullanıcının toplam mesaj sayısını hesapla (hem DB hem geçici)"""
    try:
        # Veritabanından al
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT messages FROM user_stats 
            WHERE chat_id = ? AND user_id = ?
        ''', (str(chat_id), str(user_id)))
        
        result = cursor.fetchone()
        db_count = result[0] if result else 0
        
        # Geçici sayactan al
        temp_count = user_messages.get(f"{chat_id}_{user_id}", 0)
        
        conn.close()
        return db_count + temp_count
        
    except Exception as e:
        logger.error(f"Mesaj sayım hatası: {e}")
        return "Hesaplanamadı"

# Mesaj sayacını güncelle
@client.on(events.NewMessage)
async def update_message_counter(event):
    """Mesaj sayacını güncelle"""
    if not event.is_private and event.message:
        chat_id = event.chat_id
        user_id = event.sender_id
        
        # Geçici sayaca ekle
        key = f"{chat_id}_{user_id}"
        user_messages[key] = user_messages.get(key, 0) + 1
        
        # Global istatistiklere ekle
        daily_stats["messages"][str(chat_id)] += 1
        
        # Her 10 mesajda bir veritabanını güncelle
        if user_messages[key] % 10 == 0:
            try:
                update_user_stats(chat_id, user_id)
                user_messages[key] = 0  # Geçici sayacı sıfırla
            except Exception as e:
                logger.error(f"Kullanıcı stats güncelleme hatası: {e}")

# Periyodik veritabanı güncellemesi
async def periodic_db_update():
    """Her 5 dakikada bir geçici verileri veritabanına aktar"""
    while True:
        try:
            await asyncio.sleep(300)  # 5 dakika
            
            # Kullanıcı mesajlarını güncelle
            for key, count in user_messages.items():
                if count > 0:
                    try:
                        chat_id, user_id = key.split('_')
                        update_user_stats(int(chat_id), int(user_id))
                        user_messages[key] = 0
                    except Exception as e:
                        logger.error(f"Periyodik güncelleme hatası: {e}")
            
            # İstatistikleri kaydet
            save_stats()
            
        except Exception as e:
            logger.error(f"Periyodik görev hatası: {e}")

# Grup üye sayısını al (yardımcı fonksiyon)
async def get_member_count(chat_id):
    """Grup üye sayısını al"""
    try:
        chat = await client.get_entity(chat_id)
        full_chat = await client(GetFullChannelRequest(chat))
        return full_chat.full_chat.participants_count
    except Exception as e:
        logger.error(f"Üye sayısı alma hatası: {e}")
        return "Bilinmiyor"

# Kapsamlı stat komutu (geliştirilmiş)
@client.on(events.NewMessage(pattern=r'/stats(?:@\w+)?'))
async def enhanced_stat_command(event):
    """Geliştirilmiş istatistik komutu"""
    if not await check_admin_permission(event, "edit_group"):
        await event.respond("Bu komutu kullanma yetkiniz yok.")
        return
    
    chat_id = event.chat_id
    
    try:
        chat = await event.get_chat()
        member_count = await get_member_count(chat_id)
        
        # Günlük stats
        today_stats = get_daily_stats(chat_id)
        
        # Global stats'dan da al
        global_messages = daily_stats["messages"].get(str(chat_id), 0)
        global_new_members = daily_stats["new_members"].get(str(chat_id), 0)
        global_left_members = daily_stats["left_members"].get(str(chat_id), 0)
        
        # Toplam değerleri hesapla
        total_messages = today_stats.get("messages", 0) + global_messages
        total_new = today_stats.get("new_members", 0) + global_new_members  
        total_left = today_stats.get("left_members", 0) + global_left_members
        
        net_change = total_new - total_left
        change_emoji = "📈" if net_change > 0 else "📉" if net_change < 0 else "➖"
        
        # En aktif kullanıcıları al
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, messages FROM user_stats 
            WHERE chat_id = ? AND messages > 0
            ORDER BY messages DESC LIMIT 5
        ''', (str(chat_id),))
        
        top_users = cursor.fetchall()
        conn.close()
        
        # Top kullanıcılar listesi
        top_users_text = ""
        if top_users:
            top_users_text = "\n\n**📊 En Aktif Kullanıcılar:**\n"
            for i, (user_id, msg_count) in enumerate(top_users, 1):
                try:
                    user = await client.get_entity(int(user_id))
                    name = user.first_name
                    top_users_text += f"{i}. {name}: {msg_count} mesaj\n"
                except:
                    top_users_text += f"{i}. Kullanıcı {user_id}: {msg_count} mesaj\n"
        
        report = f"📊 **GRUP İSTATİSTİKLERİ**\n\n"
        report += f"**Grup:** {chat.title}\n"
        report += f"**Tarih:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
        report += f"**👥 Üye Bilgileri:**\n"
        report += f"• Toplam Üye: {member_count}\n"
        report += f"• Günlük Değişim: {change_emoji} {net_change:+d}\n"
        report += f"• Yeni Katılanlar: +{total_new}\n"
        report += f"• Ayrılanlar: -{total_left}\n\n"
        report += f"**💬 Aktivite:**\n"
        report += f"• Bugünkü Mesajlar: {total_messages}\n"
        report += top_users_text
        
        await event.respond(report)
        
    except Exception as e:
        logger.error(f"Enhanced stat komutu hatası: {e}")
        await event.respond(f"İstatistik alınırken hata oluştu: {str(e)}")

# Bot başlangıcında çalışacak init fonksiyonu
async def initialize_bot():
    """Bot başlangıcında çalışacak fonksiyonlar"""
    try:
        # İstatistikleri yükle
        load_stats()
        
        # Veritabanını kontrol et
        init_database()
        
        # Tüm gruplara flood config ekle
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id FROM groups')
        all_groups = cursor.fetchall()
        conn.close()
        
        for (chat_id,) in all_groups:
            add_flood_config_to_group(chat_id)
        
        logger.info("Bot başarıyla başlatıldı ve yapılandırıldı")
        
    except Exception as e:
        logger.error(f"Bot başlatma hatası: {e}")

# İstatistik temizleme komutu (admin için)
@client.on(events.NewMessage(pattern=r'/clearstats(?:@\w+)?'))
async def clear_stats_command(event):
    """İstatistikleri temizle (sadece bot admin'i için)"""
    # Bot geliştiricisi kontrolü
    if event.sender_id != 123456789:  # Buraya kendi ID'nizi koyun
        return
    
    try:
        reset_daily_stats()
        
        # Tüm user stats'ları sıfırla
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM daily_stats')
        cursor.execute('UPDATE user_stats SET messages = 0')
        conn.commit()
        conn.close()
        
        await event.respond("✅ Tüm istatistikler temizlendi!")
        
    except Exception as e:
        await event.respond(f"❌ Hata: {str(e)}")

# Bot durumu komutu
@client.on(events.NewMessage(pattern=r'/botstatus(?:@\w+)?'))
async def bot_status_command(event):
    """Bot durumu ve sistem bilgileri"""
    if not await check_admin_permission(event, "edit_group"):
        return
    
    try:
        # Sistem bilgileri
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Toplam grup sayısı
        cursor.execute('SELECT COUNT(*) FROM groups')
        total_groups = cursor.fetchone()[0]
        
        # Toplam kullanıcı sayısı
        cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_stats')
        total_users = cursor.fetchone()[0]
        
        # Toplam mesaj sayısı
        cursor.execute('SELECT SUM(messages) FROM user_stats')
        total_messages = cursor.fetchone()[0] or 0
        
        # Aktif gruplar (log açık)
        cursor.execute('SELECT COUNT(*) FROM groups WHERE log_enabled = 1')
        active_groups = cursor.fetchone()[0]
        
        conn.close()
        
        # Uptime hesapla (basit)
        uptime = "Bot şu anda çalışıyor"
        
        status_text = f"🤖 **BOT DURUM RAPORU**\n\n"
        status_text += f"**📊 İstatistikler:**\n"
        status_text += f"• Toplam Grup: {total_groups}\n"
        status_text += f"• Aktif Gruplar: {active_groups}\n"
        status_text += f"• Toplam Kullanıcı: {total_users}\n"
        status_text += f"• İşlenen Mesajlar: {total_messages}\n\n"
        status_text += f"**⚡ Sistem:**\n"
        status_text += f"• Durum: {uptime}\n"
        status_text += f"• Veritabanı: SQLite ✅\n"
        status_text += f"• Türkçe Destek: Aktif ✅\n"
        status_text += f"• Son Güncelleme: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        await event.respond(status_text)
        
    except Exception as e:
        await event.respond(f"Durum raporu alınırken hata: {str(e)}")
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
/report [sebep] - Adminlere rapor gönderir

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
    
# Log channel ID kontrolü ve düzeltmesi
def fix_channel_ids():
    """Channel ID'lerini doğru formata çevir"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT chat_id, log_channel_id FROM groups WHERE log_channel_id != 0')
    for chat_id, channel_id in cursor.fetchall():
        try:
            # Eğer pozitif ise negatif yap
            if int(channel_id) > 0:
                fixed_id = -int(channel_id)
                cursor.execute('UPDATE groups SET log_channel_id = ? WHERE chat_id = ?', 
                             (fixed_id, chat_id))
                logger.info(f"Channel ID düzeltildi: {channel_id} → {fixed_id}")
        except:
            pass
    
    conn.commit()
    conn.close()

# Bu fonksiyonu bot başlarken çağırın
# main() fonksiyonunun başına ekleyin: fix_channel_ids()

# Ana fonksiyon
async def main():
    # Veritabanını başlat
    init_database()
    fix_channel_ids()
    
    # Arka plan görevleri
    asyncio.create_task(send_repeated_messages())
    asyncio.create_task(send_daily_report())
    asyncio.create_task(daily_stats_reset_task())
    asyncio.create_task(periodic_db_update())
    asyncio.create_task(cleanup_entity_cache())  # ← BU SATIRI EKLEYİN
    
    print("🚀 Bot başlatıldı!")
    print("🗄️ SQLite veritabanı hazır!")
    print("✅ Türkçe karakter desteği aktif!")
    print("🗂️ Entity cache sistemi aktif!")
    
    await client.run_until_disconnected()

# Bot'u başlat
if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
