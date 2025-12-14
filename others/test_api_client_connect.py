import asyncio
import time
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("APIClientTest")

from maim_message.client_ws_api import WebSocketClient
from maim_message.ws_config import create_client_config
from maim_message.api_message_base import (
    APIMessageBase,
    Seg,
    MessageDim,
    BaseMessageInfo,
    UserInfo,
    SenderInfo
)

# Global future to wait for reply
reply_received = None

async def test_client():
    global reply_received
    reply_received = asyncio.get_running_loop().create_future()

    # 1. Configuration
    # Assumes local server is running on 18099 (from previous logs)
    # Replace with your actual API Key
    # api_key = "mmc_OWUxZGZmNTQtMDMyYS00OTQyLTk1ZTktNzczZmFjMTc0MGeb_0bECf5ab-a3e4-4ec9-b201-726aa57098c2_352291d6c4e74da2_v1"
    api_key = "mmc_YWI4MjA3NmMtZmI4Mi00ZmRkLTkyMTUtNDk5NWQ5Yjk5OTYzXzAzODk2NGJhLTFhODItNGM0OC1hYTgyLTA5MjJlOTA0ODAzZF82ZjYwMzNmYjMyMzI0YjMzX3Yx"
    
    # WebSocket server URL
    ws_url = "ws://localhost:18040/ws"
    platform = "test_platform"
    
    logger.info(f"Configuring client for {ws_url}...")
    
    config = create_client_config(
        url=ws_url,
        api_key=api_key,
        platform=platform,
        auto_reconnect=False,
        on_message=on_message_callback
    )

    # 2. Initialize Client
    client = WebSocketClient(config)

    try:
        # 3. Start and Connect
        logger.info("Starting client...")
        await client.start()
        
        logger.info("Connecting to server...")
        connected = await client.connect()
        
        if not connected:
            logger.error("Failed to connect!")
            return

        logger.info("Connected successfully!")
        
        # 4. Construct Message
        # - Dimension: routing info
        dim = MessageDim(api_key=api_key, platform=platform)
        
        # - Segment: Content
        seg = Seg(type="text", data="你好")
        
        # - Info: Metadata
        info = BaseMessageInfo(
            platform=platform,
            message_id=f"msg_{int(time.time())}",
            time=time.time(),
            sender_info=SenderInfo(
                user_info=UserInfo(platform=platform, user_id="tester_001", user_nickname="Tester")
            )
        )
        
        msg = APIMessageBase(
            message_info=info,
            message_segment=seg,
            message_dim=dim
        )
        
        # 5. Send Message
        logger.info(f"Sending test message: {seg.data}")
        success = await client.send_message(msg)
        
        if success:
            logger.info("Message sent successfully! Waiting for reply...")
            try:
                reply = await asyncio.wait_for(reply_received, timeout=60.0)
                logger.info(f"✅ TEST PASSED: Received reply: {reply}")
            except asyncio.TimeoutError:
                logger.error("❌ TEST FAILED: Timed out waiting for reply (60s)")
        else:
            logger.warning("Message send returned False")

    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
    finally:
        # 6. Cleanup
        logger.info("Stopping client...")
        await client.stop()
        logger.info("Client stopped.")

async def on_message_callback(message: APIMessageBase, metadata: dict):
    content = message.message_segment.data
    logger.info(f"Received message from server: {content}")
    if reply_received and not reply_received.done():
        reply_received.set_result(content)

if __name__ == "__main__":
    asyncio.run(test_client())
