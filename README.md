# 廣東話音頻對齊

這是一個網頁應用程式，基於 [MunamWasi/RHYME-CTRL](https://github.com/MunamWasi/RHYME-CTRL) 修改，加入對廣東話的支持。
用於英文和廣東話的字幕與音頻對齊。也能分析英文歌詞的押韻結構，並生成帶有即時單詞高亮效果的同步影片。

## 功能特色

- **音頻與歌詞對齊** — 由 OpenAI Whisper 驅動，實現精準的單詞級時間戳
- **基於音素的韻腳檢測** — 使用 CMU 發音詞典，根據實際發音（而非拼寫）識別押韻家族
- **多種顯示模式**:
  - **Text Mode** — 無需音頻分析歌詞，查看押韻模式高亮
  - **Auto Mode** — 上傳音頻 + 歌詞，獲得同步播放
  - **Finetune Mode** — 手動調整單詞時間和押韻分組
  - **Perform Mode** — 卡拉 OK 風格實時顯示
  - **Capture Mode** — 電影級 1280×720 視圖，專為影片錄製優化
- **Video Export** — 生成帶同步高亮效果的專業 MP4 影片

## 快速開始

### 環境要求

- Python 3.9+
- FFmpeg（用於影片導出）
- 約 2GB 硬碟空間（用於 Whisper 模型）

### 安裝步驟

```bash
# 克隆倉庫
git clone https://github.com/GavinFu7/SUBTITLE-TIMEALIGN.git
cd SUBTITLE-TIMEALIGN

# 創建虛擬環境
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 安裝依賴
pip3 install -r requirements.txt

# 安裝影片錄製所需的 Playwright（可選）
pip3 install playwright moviepy
python3 -m playwright install chromium
```

### 安裝 FFmpeg:
#### macOS
```bash
brew install ffmpeg
```

#### Ubuntu/Debian
```bash
sudo apt install ffmpeg
```

#### Windows
```bash
choco install ffmpeg
```

### 運行應用

```bash
# # 激活虛擬環境
source venv/bin/activate

# 啟動 Flask 服務器
python3 app.py
```

在瀏覽器中打開 **http://localhost:5001**
