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
        command = ['yt-dlp', '--dump-json', '--no-warnings', '--quiet', video_url]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        video_info = json.loads(result.stdout)

        video_id = video_info.get('id')
        if not video_id:
            return jsonify({"error": "動画IDを取得できませんでした。URLを確認してください。"}), 500

        heatmap_data = video_info.get('heatmap')
        if not heatmap_data:
            return jsonify({"error": "この動画にはヒートマップデータが見つかりませんでした。動画が短すぎるか、YouTubeの機能による制限の可能性があります。"}), 404

        # ここからヒートマップデータの解析とシーンの結合ロジック
        
        # 1. 全てのヒートマップセグメントから最大の'value'を取得
        max_value = max(segment['value'] for segment in heatmap_data)
        
        # 2. 閾値を設定: 最大値の70%を基準とします。
        # max_valueが0の場合はデフォルト値を使用
        threshold = max_value * 0.7 if max_value > 0 else 0.5 
        
        # 3. 閾値を超えるセグメントのみをフィルタリング
        # ヒートマップデータはすでに時間順に並んでいると仮定します。
        filtered_segments = [s for s in heatmap_data if s['value'] >= threshold]

        merged_scenes = []
        if filtered_segments:
            # 最初のフィルタリングされたセグメントで現在のマージシーンを初期化
            current_merged_scene = {
                'start_time': filtered_segments[0]['start_time'],
                'end_time': filtered_segments[0]['end_time'],
                'total_value_duration': filtered_segments[0]['value'] * (filtered_segments[0]['end_time'] - filtered_segments[0]['start_time']),
                'total_duration': filtered_segments[0]['end_time'] - filtered_segments[0]['start_time'],
                'value': filtered_segments[0]['value'] # 初期値
            }
            
            # フィルタリングされたセグメントを順に処理して連続するものを結合
            for i in range(1, len(filtered_segments)):
                prev_segment = filtered_segments[i-1]
                current_segment = filtered_segments[i]

                # 現在のセグメントが直前のセグメント（または結合中のシーン）と連続しているかチェック
                # 浮動小数点数の比較なので、わずかな誤差を許容することも考えられますが、
                # YouTubeのヒートマップは厳密な区切りになっていることが多いです。
                if current_segment['start_time'] == current_merged_scene['end_time']:
                    # 連続している場合、現在のマージシーンを延長し、valueを更新
                    current_merged_scene['end_time'] = current_segment['end_time']
                    segment_duration = current_segment['end_time'] - current_segment['start_time']
                    current_merged_scene['total_value_duration'] += (current_segment['value'] * segment_duration)
                    current_merged_scene['total_duration'] += segment_duration
                    current_merged_scene['value'] = current_merged_scene['total_value_duration'] / current_merged_scene['total_duration']
                else:
                    # 連続していない場合、現在のマージシーンを確定してリストに追加
                    merged_scenes.append(current_merged_scene)
                    # 新しいマージシーンを現在のセグメントで初期化
                    current_merged_scene = {
                        'start_time': current_segment['start_time'],
                        'end_time': current_segment['end_time'],
                        'total_value_duration': current_segment['value'] * (current_segment['end_time'] - current_segment['start_time']),
                        'total_duration': current_segment['end_time'] - current_segment['start_time'],
                        'value': current_segment['value']
                    }
            
            # 最後のマージシーンをリストに追加
            merged_scenes.append(current_merged_scene)

        # 結合されたシーンを 'value' の降順でソートします。
        # これにより、最もリプレイ回数が多い（と推定される）シーンがリストの先頭に来ます。
        merged_scenes.sort(key=lambda x: x['value'], reverse=True)

        # 抽出されたシーンの情報を、フロントエンドで表示しやすい形式に変換し、
        # YouTubeの埋め込みURLを追加します。
        formatted_scenes = []
        for scene in merged_scenes: # merged_scenesを使用
            start_sec_int = int(scene['start_time'])
            end_sec_int = int(scene['end_time'])

            start_min = start_sec_int // 60
            start_sec = start_sec_int % 60
            end_min = end_sec_int // 60
            end_sec = end_sec_int % 60

            embed_url = f"https://www.youtube.com/embed/{video_id}?start={start_sec_int}&end={end_sec_int}&autoplay=1"

            formatted_scenes.append({
                'start_time_raw': scene['start_time'],
                'end_time_raw': scene['end_time'],
                'start_time_formatted': f"{start_min:02d}:{start_sec:02d}",
                'end_time_formatted': f"{end_min:02d}:{end_sec:02d}",
                'value': f"{scene['value']:.4f}",
                'embed_url': embed_url
            })

        return jsonify({
            "video_title": video_info.get('title', '不明なタイトル'),
            "thumbnail_url": video_info.get('thumbnail', ''),
            "scenes": formatted_scenes
        })

    except subprocess.CalledProcessError as e:
        app.logger.error(f"yt-dlp実行エラー: {e.stderr}")
        return jsonify({"error": f"動画の解析に失敗しました。URLを確認してください。エラー: {e.stderr.strip()}"}), 500
    except json.JSONDecodeError:
        return jsonify({"error": "yt-dlpの出力が不正なJSON形式でした。"}), 500
    except Exception as e:
        app.logger.error(f"予期せぬエラー: {e}")
        return jsonify({"error": f"サーバーエラーが発生しました: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
