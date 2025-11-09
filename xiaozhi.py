"""
Xiaozhi Adapter - Pure Xiaozhishop Proxy Version
Lấy cả audio và lyric từ Xiaozhishop, cache và proxy lại
"""

from flask import Flask, request, jsonify, Response
import requests
from urllib.parse import quote, unquote
import os
from collections import OrderedDict
import logging
import json
import warnings
import html

# Tắt SSL warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# Configuration
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # Hỗ trợ tiếng Việt

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== CẤU HÌNH API =====
class Config:
    PORT = int(os.getenv('PORT', 5005))  # Port khác với Xiaozhishop
    
    # Xiaozhishop config (nguồn chính)
    XIAOZHISHOP_HOST = os.getenv('XIAOZHISHOP_HOST', 'www.xiaozhishop.xyz')
    XIAOZHISHOP_PORT = int(os.getenv('XIAOZHISHOP_PORT', 5005))
    XIAOZHISHOP_HTTPS = os.getenv('XIAOZHISHOP_HTTPS', 'false').lower() == 'true'
    
    CACHE_MAX_SIZE = int(os.getenv('CACHE_MAX_SIZE', 20))
    REQUEST_TIMEOUT = 30
    
    @property
    def XIAOZHISHOP_BASE_URL(self):
        protocol = "https" if self.XIAOZHISHOP_HTTPS else "http"
        return f"{protocol}://{self.XIAOZHISHOP_HOST}:{self.XIAOZHISHOP_PORT}"

config = Config()

# Cache đơn giản
audio_cache = OrderedDict()
lyric_cache = OrderedDict()

# ===== HELPER FUNCTIONS =====
def normalize_query(text):
    """Chuẩn hóa query để tìm kiếm"""
    return ' '.join(text.split())

def encode_vietnamese(text):
    """Encode tiếng Việt cho URL"""
    return quote(text, safe='')

def add_to_cache(song_id, data, cache_type='audio'):
    """
    Thêm vào cache với giới hạn kích thước
    cache_type: 'audio' hoặc 'lyric'
    """
    target_cache = audio_cache if cache_type == 'audio' else lyric_cache
    
    if song_id in target_cache:
        target_cache.move_to_end(song_id)
    else:
        target_cache[song_id] = data
        if len(target_cache) > config.CACHE_MAX_SIZE:
            removed_key = next(iter(target_cache))
            target_cache.popitem(last=False)
            logger.info(f"🗑️ Removed {removed_key} from {cache_type} cache")

def generate_song_id(title, artist):
    """Tạo song_id từ title và artist"""
    import hashlib
    key = f"{title}_{artist}".lower().strip()
    return hashlib.md5(key.encode()).hexdigest()[:12]

# ===== MAIN ENDPOINT =====
@app.route('/stream_pcm', methods=['GET'])
def stream_pcm():
    """
    Endpoint chính để tìm kiếm và trả về thông tin bài hát
    Query params: song, artist (optional)
    """
    try:
        song = request.args.get('song', '').strip()
        artist = request.args.get('artist', '').strip()

        if not song:
            return jsonify({'error': 'Missing song parameter'}), 400

        logger.info(f"🔍 Searching: \"{song}\" by \"{artist}\"")

        # Tạo query string
        search_query = normalize_query(f"{song} {artist}" if artist else song)
        encoded_query = encode_vietnamese(search_query)
        
        # ===== GỌI XIAOZHISHOP API =====
        xiaozhi_url = f"{config.XIAOZHISHOP_BASE_URL}/stream_pcm?song={encoded_query}"
        if artist:
            xiaozhi_url += f"&artist={encode_vietnamese(artist)}"
        
        logger.info(f"📡 Xiaozhishop API URL: {xiaozhi_url}")
        
        response = requests.get(
            xiaozhi_url,
            timeout=config.REQUEST_TIMEOUT,
            headers={'User-Agent': 'Xiaozhi-Adapter/1.0'},
            verify=False
        )
        
        logger.info(f"📥 Xiaozhishop Response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"❌ Xiaozhishop returned {response.status_code}")
            return jsonify({
                'error': 'Song not found',
                'title': song,
                'artist': artist or 'Unknown'
            }), 404
        
        data = response.json()
        
        # Parse response từ Xiaozhishop
        # Format: {"artist": "...", "audio_url": "...", "cover_url": "...", 
        #          "duration": 279, "lyric_url": "...", "title": "..."}
        
        title = data.get('title', song)
        artist_name = data.get('artist', artist or 'Unknown')
        audio_url = data.get('audio_url', '')
        lyric_url = data.get('lyric_url', '')
        duration = data.get('duration', 0)
        from_cache = data.get('from_cache', False)
        
        logger.info(f"✅ Found: {title} - {artist_name}")
        logger.info(f"   Audio URL: {audio_url}")
        logger.info(f"   Lyric URL: {lyric_url}")
        logger.info(f"   From cache: {from_cache}")
        
        if not audio_url:
            logger.error(f"❌ No audio_url in response")
            return jsonify({'error': 'No audio URL available'}), 404
        
        # Tạo song_id
        song_id = generate_song_id(title, artist_name)
        
        # ===== PRE-DOWNLOAD AUDIO TỪ XIAOZHISHOP =====
        if audio_url and song_id:
            try:
                # Tạo full URL nếu là relative path
                if audio_url.startswith('http'):
                    full_audio_url = audio_url
                else:
                    full_audio_url = f"{config.XIAOZHISHOP_BASE_URL}{audio_url}"
                
                logger.info(f"⬇️ Pre-downloading audio for {song_id}...")
                logger.info(f"   Full URL: {full_audio_url}")
                
                audio_response = requests.get(
                    full_audio_url,
                    timeout=120,
                    headers={'User-Agent': 'Xiaozhi-Adapter/1.0'},
                    verify=False,
                    stream=False
                )
                
                if audio_response.status_code == 200:
                    audio_buffer = audio_response.content
                    add_to_cache(song_id, audio_buffer, 'audio')
                    logger.info(f"✅ Downloaded audio: {len(audio_buffer)} bytes")
                else:
                    logger.warning(f"⚠️ Failed to download audio: {audio_response.status_code}")
            except Exception as e:
                logger.error(f"❌ Failed to pre-download audio {song_id}: {str(e)}")

        # ===== PRE-DOWNLOAD LYRIC TỪ XIAOZHISHOP =====
        if lyric_url and song_id:
            try:
                # Tạo full URL nếu là relative path
                if lyric_url.startswith('http'):
                    full_lyric_url = lyric_url
                else:
                    full_lyric_url = f"{config.XIAOZHISHOP_BASE_URL}{lyric_url}"
                
                logger.info(f"⬇️ Pre-downloading lyric for {song_id}...")
                logger.info(f"   Full URL: {full_lyric_url}")
                
                lyric_response = requests.get(
                    full_lyric_url,
                    timeout=30,
                    headers={'User-Agent': 'Xiaozhi-Adapter/1.0'},
                    verify=False
                )
                
                if lyric_response.status_code == 200:
                    lyric_content = lyric_response.text
                    
                    # Decode HTML entities (như &apos; → ')
                    lyric_content = html.unescape(lyric_content)
                    
                    add_to_cache(song_id, lyric_content, 'lyric')
                    logger.info(f"✅ Downloaded lyric: {len(lyric_content)} chars")
                else:
                    logger.warning(f"⚠️ Failed to download lyric: {lyric_response.status_code}")
            except Exception as e:
                logger.error(f"❌ Failed to pre-download lyric {song_id}: {str(e)}")

        # ===== TRẢ VỀ RESPONSE =====
        result = {
            'title': title,
            'artist': artist_name,
            'audio_url': f'/proxy_audio?id={song_id}',
            'lyric_url': f'/proxy_lyric?id={song_id}' if lyric_url else None,
            'duration': duration,
            'from_cache': from_cache,
            'song_id': song_id
        }

        logger.info(f"✅ Returning: {title} - {artist_name}")
        if lyric_url:
            logger.info(f"📝 With lyric available")
        
        return jsonify(result)

    except requests.RequestException as e:
        logger.error(f"❌ Request error: {str(e)}")
        return jsonify({'error': f'API request failed: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error'}), 500

# ===== PROXY AUDIO =====
@app.route('/proxy_audio', methods=['GET'])
def proxy_audio():
    """
    Proxy audio stream từ Xiaozhishop cache
    Query params: id
    """
    try:
        song_id = request.args.get('id', '')

        if not song_id:
            return jsonify({'error': 'Missing id parameter'}), 400

        logger.info(f"🎵 Serving audio for song ID: {song_id}")

        # Kiểm tra cache
        if song_id in audio_cache:
            audio_buffer = audio_cache[song_id]
            logger.info(f"✅ Serving {len(audio_buffer)} bytes from cache")
            
            return Response(
                audio_buffer,
                mimetype='audio/mpeg',
                headers={
                    'Content-Length': str(len(audio_buffer)),
                    'Accept-Ranges': 'bytes',
                    'Cache-Control': 'public, max-age=86400',
                    'Access-Control-Allow-Origin': '*'
                }
            )

        # Nếu không có trong cache
        logger.warning(f"⚠️ Song {song_id} not in audio cache")
        return jsonify({'error': 'Audio not in cache, please search again'}), 404

    except Exception as e:
        logger.error(f"❌ Proxy audio error: {str(e)}")
        return jsonify({'error': 'Failed to proxy audio'}), 500

# ===== PROXY LYRIC =====
@app.route('/proxy_lyric', methods=['GET'])
def proxy_lyric():
    """
    Proxy lyric content từ Xiaozhishop cache
    Query params: 
      - id: song ID
      - format: 'text' (default) hoặc 'json'
    """
    try:
        song_id = request.args.get('id', '')
        format_type = request.args.get('format', 'text')  # 'text' hoặc 'json'

        if not song_id:
            return jsonify({'error': 'Missing id parameter'}), 400

        logger.info(f"📝 Serving lyric for song ID: {song_id}, format: {format_type}")

        # Kiểm tra cache
        if song_id not in lyric_cache:
            logger.warning(f"⚠️ Lyric for song {song_id} not in cache")
            return jsonify({'error': 'Lyric not in cache, please search again'}), 404

        lyric_content = lyric_cache[song_id]
        logger.info(f"✅ Serving lyric from cache ({len(lyric_content)} chars)")
        
        # Nếu request muốn JSON format, parse LRC
        if format_type == 'json':
            try:
                lines = lyric_content.strip().split('\n')
                parsed_lyrics = []
                
                for line in lines:
                    # LRC format: [mm:ss.xx]text hoặc [mm:ss]text
                    if line.startswith('[') and ']' in line:
                        try:
                            time_part = line[1:line.index(']')]
                            text_part = line[line.index(']')+1:].strip()
                            
                            # Bỏ qua metadata lines (ar:, ti:, al:, etc)
                            if ':' in time_part and not any(time_part.startswith(x) for x in ['ar:', 'ti:', 'al:', 'by:', 'offset:']):
                                parts = time_part.split(':')
                                if len(parts) == 2:
                                    minutes = int(parts[0])
                                    seconds = float(parts[1])
                                    time_ms = int((minutes * 60 + seconds) * 1000)
                                    
                                    if text_part:  # Chỉ thêm nếu có text
                                        parsed_lyrics.append({
                                            'time': time_ms,
                                            'text': text_part
                                        })
                        except (ValueError, IndexError):
                            continue
                
                return jsonify({
                    'success': True,
                    'format': 'json',
                    'lyrics': parsed_lyrics
                })
            
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse LRC to JSON: {str(e)}")
                # Fallback to raw text
                return jsonify({
                    'success': True,
                    'format': 'text',
                    'lyric': lyric_content
                })
        
        # Trả về raw LRC text (default)
        return Response(
            lyric_content,
            mimetype='text/plain',
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'Cache-Control': 'public, max-age=86400',
                'Access-Control-Allow-Origin': '*'
            }
        )

    except Exception as e:
        logger.error(f"❌ Proxy lyric error: {str(e)}")
        return jsonify({'error': 'Failed to proxy lyric'}), 500

# ===== HEALTH CHECK =====
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'source': 'xiaozhishop',
        'audio_cache_size': len(audio_cache),
        'lyric_cache_size': len(lyric_cache),
        'cached_songs': list(audio_cache.keys()),
        'cached_lyrics': list(lyric_cache.keys()),
        'config': {
            'port': config.PORT,
            'xiaozhishop_url': config.XIAOZHISHOP_BASE_URL,
            'cache_max_size': config.CACHE_MAX_SIZE
        }
    })

# ===== CONFIG ENDPOINT =====
@app.route('/config', methods=['GET', 'POST'])
def manage_config():
    """
    Xem và cập nhật cấu hình
    GET: Xem cấu hình hiện tại
    POST: Cập nhật cấu hình (JSON body)
    """
    if request.method == 'GET':
        return jsonify({
            'xiaozhishop': {
                'host': config.XIAOZHISHOP_HOST,
                'port': config.XIAOZHISHOP_PORT,
                'https': config.XIAOZHISHOP_HTTPS,
                'full_url': config.XIAOZHISHOP_BASE_URL
            },
            'cache_max_size': config.CACHE_MAX_SIZE,
            'server_port': config.PORT
        })
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            
            if 'xiaozhishop_host' in data:
                config.XIAOZHISHOP_HOST = data['xiaozhishop_host']
                logger.info(f"✅ Updated XIAOZHISHOP_HOST to {config.XIAOZHISHOP_HOST}")
            
            if 'xiaozhishop_port' in data:
                config.XIAOZHISHOP_PORT = int(data['xiaozhishop_port'])
                logger.info(f"✅ Updated XIAOZHISHOP_PORT to {config.XIAOZHISHOP_PORT}")
            
            if 'xiaozhishop_https' in data:
                config.XIAOZHISHOP_HTTPS = bool(data['xiaozhishop_https'])
                logger.info(f"✅ Updated XIAOZHISHOP_HTTPS to {config.XIAOZHISHOP_HTTPS}")
            
            if 'cache_max_size' in data:
                config.CACHE_MAX_SIZE = int(data['cache_max_size'])
                logger.info(f"✅ Updated CACHE_MAX_SIZE to {config.CACHE_MAX_SIZE}")
            
            return jsonify({
                'success': True,
                'message': 'Config updated successfully',
                'config': {
                    'xiaozhishop_url': config.XIAOZHISHOP_BASE_URL,
                    'cache_max_size': config.CACHE_MAX_SIZE
                }
            })
        
        except Exception as e:
            logger.error(f"❌ Config update error: {str(e)}")
            return jsonify({'error': str(e)}), 400

# ===== CLEAR CACHE ENDPOINT =====
@app.route('/clear_cache', methods=['POST'])
def clear_cache():
    """
    Xóa cache (audio, lyric, hoặc cả hai)
    POST body: {"type": "all|audio|lyric"}
    """
    try:
        data = request.get_json() or {}
        cache_type = data.get('type', 'all')  # 'audio', 'lyric', hoặc 'all'
        
        if cache_type in ['audio', 'all']:
            audio_cache.clear()
            logger.info("🗑️ Cleared audio cache")
        
        if cache_type in ['lyric', 'all']:
            lyric_cache.clear()
            logger.info("🗑️ Cleared lyric cache")
        
        return jsonify({
            'success': True,
            'message': f'Cleared {cache_type} cache',
            'audio_cache_size': len(audio_cache),
            'lyric_cache_size': len(lyric_cache)
        })
    
    except Exception as e:
        logger.error(f"❌ Clear cache error: {str(e)}")
        return jsonify({'error': str(e)}), 400

# ===== MAIN =====
if __name__ == '__main__':
    print("=" * 70)
    print(f"🎵 Xiaozhi Adapter (Pure Xiaozhishop Proxy) on port {config.PORT}")
    print("=" * 70)
    print(f"📡 Source: {config.XIAOZHISHOP_BASE_URL}")
    print(f"   └─ Audio & Lyric from Xiaozhishop")
    print(f"💾 Cache: max {config.CACHE_MAX_SIZE} songs (audio + lyric)")
    print("=" * 70)
    print("\n📝 Endpoints:")
    print(f"   - GET  /stream_pcm?song=<name>&artist=<artist>")
    print(f"          → Search and get song info")
    print(f"   - GET  /proxy_audio?id=<id>")
    print(f"          → Stream audio from cache")
    print(f"   - GET  /proxy_lyric?id=<id>")
    print(f"          → Get lyric (text format)")
    print(f"   - GET  /proxy_lyric?id=<id>&format=json")
    print(f"          → Get lyric (JSON format)")
    print(f"   - GET  /health")
    print(f"          → Health check")
    print(f"   - GET  /config")
    print(f"          → View config")
    print(f"   - POST /config")
    print(f"          → Update config")
    print(f"   - POST /clear_cache")
    print(f"          → Clear cache")
    print("=" * 70)
    print("\n💡 Example:")
    print(f"   curl 'http://localhost:{config.PORT}/stream_pcm?song=Đừng Làm Trái Tim Anh Đau'")
    print("=" * 70)
    print("\n🚀 Server starting...\n")
    
    app.run(
        host='0.0.0.0',
        port=config.PORT,
        debug=False,
        threaded=True
)
