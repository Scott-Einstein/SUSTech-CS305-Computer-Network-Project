from util import *
import fractions
from datetime import datetime, timedelta

import tkinter as tk
from tkinter import messagebox
from PIL import ImageTk
import asyncio
import config
import sys
import asyncio


class ConferenceClient:
    def __init__(self,):
        # sync client
        self.is_working = True
        self.server_addr = None  # server addr
        self.on_meeting = False  # status
        self.conns = None  # you may need to maintain multiple conns for a single conference
        self.support_data_types = []  # for some types of data
        self.share_data = {}

        self.conference_info = None  # you may need to save and update some conference_info regularly

        self.recv_data = None  # you may need to save received streamd data from other clients in conference
        
        self.pc = RTCPeerConnection() #WebRTC连接
        self.username=None

        self.play_buffer = asyncio.Queue()


        self.video_frame_queue = asyncio.Queue(maxsize=10)  # 队列用于缓存视频帧，最大缓存为10帧
        self.running = True  # 控制是否继续接收视频帧

        self.audio_frame_queue = asyncio.Queue(maxsize=100)  # 缓存音频帧，最大缓存为10帧




    async def start_conference(self, ip, port):
        '''
        init conns when create or join a conference with necessary conference_info
        and
        start necessary running task for conference
        '''

        # Create new RTCPeerConnection and DataChannel
        self.pc = RTCPeerConnection()  # Create a new peer connection

        # 创建WebRTC数据通道,监听open和message实践
        self.channel = self.pc.createDataChannel("chat")
        self.channel.on("open")
        self.channel.on("message", lambda message: print(f"Received message: {message}"))

        # 创建音视频轨道
        self.video_track = VideoStreamTrack()
        self.pc.addTrack(self.video_track)
        print("[INFO] Video DataChannel open")


        self.audio_track = MicrophoneStreamTrack()
        self.pc.addTrack(self.audio_track)
        print("[INFO] Audio DataChannel open")
        

        # 当服务器创建了数据通道时，开始监听从服务器创建的数据通道
        @self.pc.on('datachannel')
        def on_datachannel(channel):
            print(f"DataChannel created by server: {channel.label}")

            @channel.on("message")
            def on_message(message):
                try:
                    # 如果接收到的是 JSON 格式的消息
                    message_data = json.loads(message)  # 解析 JSON 字符串

                    # 从字典中提取发送人、时间戳和消息内容
                    # addr = message_data.get("addr", "Unknown")  # 提取发送人，若没有则默认"Unknown"
                    timestamp = message_data.get("timestamp", "Unknown")  # 提取时间戳，若没有则默认"Unknown"
                    content = message_data.get("message", "No message")  # 提取消息内容，若没有则默认"无消息"

                    # 打印接收到的消息
                    print(f"Message from client2 at {timestamp}: {content}")

                    # 在GUI中显示消息
                    # self.gui.display_received_message(f"Message from {addr} at {timestamp}: {content}")


                except json.JSONDecodeError:
                    print(f"Received invalid message format: {message}")

        # 监听ICE连接状态变化
        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

        # 处理远程音视频轨道
        @self.pc.on("track")
        async def on_track(track):
            if track.kind == "video":
                print("[INFO] Received video track from client.")
                asyncio.create_task(self.handle_video_track(track))
                # await asyncio.gather(
                #     self.handle_video(track),  # 处理接收视频
                #     self.display_video()  # 显示视频
                # )
            elif track.kind == "audio":
                print("[INFO] Received audio track from client.")
                asyncio.create_task(self.handle_audio_track(track,play_buffer))
                # await asyncio.gather(
                #     self.handle_audio_track(track),  # 处理接收音频
                #     self.play_audio()  # 播放音频
                # )


        # 与服务器连接并处理消息
        await self.connect(ip, port)



    async def handle_video(self, track):
        """接收视频帧并将其放入队列"""
        while self.running:
            frame = await track.recv()
            await self.video_frame_queue.put(frame)  # 将帧放入队列
            # print("Frame received and queued.")

    async def display_video(self):
        """显示视频帧，消费队列中的视频帧"""
        while self.running:
            frame = await self.video_frame_queue.get()  # 从队列中获取帧
            img = frame.to_ndarray(format="bgr24")  # 转换为OpenCV格式的帧
            cv2.imshow("Client2", img)  # 显示帧
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.running = False  # 退出循环
                break


    async def handle_video_track(self, track):
        """处理远程视频轨道,接受视频帧并显示"""
        while True:
            try:
                frame = await track.recv()  # 接收远程视频帧
                if isinstance(frame, VideoFrame):
                    frame = frame.to_ndarray(format="bgr24")
                cv2.imshow("Client1 Frame", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            except Exception as e:
                print(f"[ERROR] Video track handling failed: {e}")
                break


    async def handle_audio_track(self, track, play_buffer):
        """处理远程音频轨道"""
        while True:
            try:
                frame = await track.recv()

                pcm_data = audio_frame_to_data(frame)
                streamout.write(pcm_data)

            except Exception as e:
                print(f"[ERROR] Audio track handling failed: {e}")
                break
    

    async def play_audio(self):
        """播放音频帧，消费队列中的音频帧"""
        while self.running:
            try:
                # 从队列中获取音频帧
                frame = await self.audio_frame_queue.get()

                pcm_data = audio_frame_to_data(frame)  # 假设 audio_frame_to_data 函数将音频帧转换为 PCM 数据

                # 播放音频数据
                streamout.write(pcm_data)  # 写入音频输出流
                # print("Audio frame played.")

                await asyncio.sleep(len(pcm_data) / RATE)  # 控制帧率

            except Exception as e:
                print(f"[ERROR] Audio playback failed: {e}")
                break
    

    async def start(self):
        """
        execute functions based on the command line input
        """
        # 非阻塞地获取用户输入
        async def async_input(prompt):
            """ 非阻塞的 input() 方法 """
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, input, prompt)
        

        await self.start_conference(SERVER_IP, MAIN_SERVER_PORT)
    
        while True:

            # cmd_input = input(f'({status}) Please enter a operation (enter "?" to help): ').strip().lower()
            cmd_input = await async_input('Please enter an operation (enter "?" to help): ')
            cmd_input = cmd_input.strip().lower()
            fields = cmd_input.split(maxsplit=1)
 

            if len(fields) == 2 and fields[0] == 'send':
                if self.channel and self.channel.readyState == "open":
                    # 获取当前时间
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 格式化时间为可读字符串

                    # 创建包含发送人和时间戳的消息内容
                    enhanced_message = {
                        # "addr": addr,  # 发送人
                        "timestamp": timestamp,  # 时间戳
                        "message": fields[1]  # 原始消息
                    }
                    # 将消息转换为 JSON 格式
                    enhanced_message_json = json.dumps(enhanced_message)
                    self.channel.send(enhanced_message_json)
                else:
                    print("data channel has been closed")

            elif len(fields) == 2 and fields[0] == 'switch':
                # print(f"voice: {voice},play: {play},screen:{screen},camare:{camare}")
                global screen, camare, voice, play
                if(fields[1] == 'voice'):
                    voice = not voice
                elif(fields[1] == 'screen'):
                    screen = not screen
                elif(fields[1] == 'camare'):
                    camare = not camare
                    print(f"camare: {camare}")
                elif(fields[1] == 'play'):
                    play = not play
                else:
                    print(f'[Warn]: Unrecognized cmd_input {cmd_input}')
            else:
                print(f'[Warn]: Unrecognized cmd_input {cmd_input}')
        


    async def connect(self, ip, port):
        """
        与会议服务器建立连接、发送 SDP提议、以及接收 SDP 答复
        """
        reader, writer = await asyncio.open_connection(ip, port)

        # 创建 SDP Offer
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # 发送 SDP Offer
        
        writer.write(self.pc.localDescription.sdp.encode())
        await writer.drain()

        # 从服务器接收 SDP Answer 数据并解码
        data = await reader.read(16384)
        answer_sdp = data.decode()
        # 将服务器的 SDP Answer 设置为客户端的远程描述。
        answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
        await self.pc.setRemoteDescription(answer)


        # print(f"[INFO] Sent offer to server and received answer.")
    


class VideoStreamTrack(VideoStreamTrack):
    """
    自定义视频track
    """
    kind = "video"
    def __init__(self):
        super().__init__()
        self.frame_count = 0

    async def recv(self):
        """捕获图像数据并生成图像帧"""
        try:
            await asyncio.sleep(0.2)
            self.frame_count += 1

            # video_frame = capture_video_frame()

            global screen,camare,voice,play  # 明确声明这是全局变量

            # print(f"camare:{camare}")
            if camare and not screen:
                # camare 不需要BGR转换
                frame_bgr = np.array(capture_camera())
            elif not camare and screen:
                # screen 需要bgr转换
                frame_np = np.array(capture_screen())
                # 转换为 BGR 格式
                frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)
            elif camare and screen:
                # cv2 均衡化亮度
                camare_img = capture_camera()
                screen_img = capture_screen()
                frame_bgr =  overlay_camera_image(camare_img, screen_img)
            else:
                frame_bgr = cv2.imread(BG_PATH)

            # 调整为 720p 分辨率
            frame_resized = cv2.resize(frame_bgr, window_resolution, interpolation=cv2.INTER_LINEAR)
            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            video_frame = VideoFrame.from_ndarray(frame_rgb)


            video_frame.pts = self.frame_count
            video_frame.time_base = fractions.Fraction(1, 30)
            return video_frame
        except Exception as e:
            print(f"[Error] Video capture error: {e}")



class MicrophoneStreamTrack(AudioStreamTrack):
    """
    自定义音频track
    """
    kind = "audio"
    def __init__(self):
        super().__init__()
        self.frame_count = 0  
    
    async def recv(self):
        """捕获音频数据并生成音频帧"""
        try:
            await asyncio.sleep(0.05)

            self.frame_count += 1
            if voice:
                data = streamin.read(CHUNK, exception_on_overflow=False)
            else:
                data = b'\x00' * CHUNK * CHANNELS * 2\

            # 将 PCM 数据封装为 AudioFrame
            audio_frame = data_to_audio_frame(data, sample_rate=RATE, channels=CHANNELS)

            audio_frame.pts = self.frame_count
            audio_frame.sample_rate = RATE
            audio_frame.time_base = fractions.Fraction(1, RATE)

            # pcm_data = audio_frame_to_data(audio_frame)
            # streamout.write(pcm_data)
            # print(f"[INFO] Sending audio frame {self.frame_count}.")

            return audio_frame
        except Exception as e:
            print(f"[Error] Audio capture error: {e}")


if __name__ == '__main__':
    client1 = ConferenceClient()
    client1.server_addr = (SERVER_IP, MAIN_SERVER_PORT)
    asyncio.run(client1.start())  # Start the event loop with asyncio.run()



