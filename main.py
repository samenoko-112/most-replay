import subprocess
import json
import os
from flask import Flask, render_template, request, jsonify

# Flaskアプリケーションの初期化
app = Flask(__name__)

@app.route('/')
def index():
    """
    ルートURL ('/') にアクセスされたときに、index.htmlテンプレートをレンダリングします。
    これがウェブアプリケーションのメインページになります。
    """
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_video():
    """
    動画URLを受け取り、yt-dlpを使用して動画のメタデータを解析し、
    ヒートマップデータに基づいてリプレイ回数が多いシーンを特定します。
    結果はJSON形式でフロントエンドに返されます。
    """
    # POSTリクエストから動画URLを取得
    video_url = request.form.get('video_url')
    if not video_url:
        # URLが提供されていない場合はエラーを返す
        return jsonify({"error": "動画URLを入力してください。"}), 400

    try:
        # yt-dlpを実行して動画のJSONメタデータを取得します。
        # '--dump-json': メタデータをJSON形式で標準出力に出力
        # '--no-warnings': 不要な警告メッセージを抑制
        # '--quiet': 進行状況の表示を抑制し、出力はJSONのみにする
        command = ['yt-dlp', '--dump-json', '--no-warnings', '--quiet', video_url]
        
        # サブプロセスとしてyt-dlpを実行し、その出力をキャプチャします。
        # 'text=True': 出力をテキストとして扱う
        # 'check=True': コマンドがエラーコードで終了した場合にCalledProcessErrorを発生させる
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        
        # yt-dlpの標準出力をJSONとして解析します
        video_info = json.loads(result.stdout)

        # 動画IDを取得します。これは埋め込みURLの生成に必要です。
        video_id = video_info.get('id')
        if not video_id:
            # 動画IDが取得できない場合はエラーを返す
            return jsonify({"error": "動画IDを取得できませんでした。URLを確認してください。"}), 500

        # ヒートマップデータを抽出します。
        # ヒートマップデータは、動画のどの部分がどれだけ視聴されたかを示す値のリストです。
        heatmap_data = video_info.get('heatmap')
        if not heatmap_data:
            # ヒートマップデータが見つからない場合はエラーを返す
            return jsonify({"error": "この動画にはヒートマップデータが見つかりませんでした。動画が短すぎるか、YouTubeの機能による制限の可能性があります。"}), 404

        # ヒートマップデータからリプレイ回数が多いシーンを特定します。
        # ここでは、'value'が最も高いセグメントと、その最大値の70%以上の'value'を持つセグメントを抽出します。
        highlight_scenes = []
        if heatmap_data:
            # 全てのヒートマップセグメントから最大の'value'を取得
            max_value = max(segment['value'] for segment in heatmap_data)
            
            # 閾値を設定: 最大値の70%を基準とします。
            # max_valueが0の場合は無限ループを防ぐため、デフォルトの0.5を使用
            threshold = max_value * 0.7 if max_value > 0 else 0.5 
            
            # ヒートマップデータを走査し、閾値を超えるセグメントを抽出
            for segment in heatmap_data:
                if segment['value'] >= threshold:
                    highlight_scenes.append({
                        'start_time': segment['start_time'],
                        'end_time': segment['end_time'],
                        'value': segment['value']
                    })
        
        # ここから追加・変更されたロジック:
        # 抽出されたシーンを 'value' の降順でソートします。
        # これにより、最もリプレイ回数が多い（と推定される）シーンがリストの先頭に来ます。
        highlight_scenes.sort(key=lambda x: x['value'], reverse=True)

        # 抽出されたシーンの情報を、フロントエンドで表示しやすい形式に変換し、
        # YouTubeの埋め込みURLを追加します。
        formatted_scenes = []
        for scene in highlight_scenes:
            # 開始時間と終了時間を秒単位の整数に変換
            start_sec_int = int(scene['start_time'])
            end_sec_int = int(scene['end_time'])

            # 秒を分:秒形式に変換
            start_min = start_sec_int // 60
            start_sec = start_sec_int % 60
            end_min = end_sec_int // 60
            end_sec = end_sec_int % 60

            # YouTubeの埋め込みURLを生成します。
            # 'embed/' の後に動画ID、'?start=N&end=M&autoplay=1' で開始・終了時間と自動再生を指定
            embed_url = f"https://www.youtube.com/embed/{video_id}?start={start_sec_int}&end={end_sec_int}&autoplay=1"

            formatted_scenes.append({
                'start_time_raw': scene['start_time'], # 生の開始時間（秒）
                'end_time_raw': scene['end_time'],     # 生の終了時間（秒）
                'start_time_formatted': f"{start_min:02d}:{start_sec:02d}", # フォーマット済み開始時間
                'end_time_formatted': f"{end_min:02d}:{end_sec:02d}",     # フォーマット済み終了時間
                'value': f"{scene['value']:.4f}", # 'value'を小数点以下4桁に整形
                'embed_url': embed_url # 生成された埋め込みURL
            })

        # 解析結果をJSON形式でフロントエンドに返します
        return jsonify({
            "video_title": video_info.get('title', '不明なタイトル'), # 動画タイトル
            "thumbnail_url": video_info.get('thumbnail', ''),      # サムネイルURL
            "scenes": formatted_scenes # 抽出されたハイライトシーンのリスト
        })

    except subprocess.CalledProcessError as e:
        # yt-dlpの実行中にエラーが発生した場合
        app.logger.error(f"yt-dlp実行エラー: {e.stderr}")
        return jsonify({"error": f"動画の解析に失敗しました。URLを確認してください。エラー: {e.stderr.strip()}"}), 500
    except json.JSONDecodeError:
        # yt-dlpの出力が有効なJSON形式でなかった場合
        return jsonify({"error": "yt-dlpの出力が不正なJSON形式でした。"}), 500
    except Exception as e:
        # その他の予期せぬエラーが発生した場合
        app.logger.error(f"予期せぬエラー: {e}")
        return jsonify({"error": f"サーバーエラーが発生しました: {str(e)}"}), 500

if __name__ == '__main__':
    # アプリケーションをデバッグモードで実行します。
    # 本番環境では debug=False に設定してください。
    app.run(host='0.0.0.0', debug=True)
