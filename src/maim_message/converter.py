"""消息格式转换器模块

提供 MessageBase 和 APIMessageBase 之间的标准化双向转换。
"""

from typing import Optional
import time

from .message_base import (
    MessageBase,
    BaseMessageInfo as LegacyBaseMessageInfo,
    Seg as LegacySeg,
    GroupInfo as LegacyGroupInfo,
    UserInfo as LegacyUserInfo,
    SenderInfo as LegacySenderInfo,
    ReceiverInfo as LegacyReceiverInfo,
    FormatInfo as LegacyFormatInfo,
    TemplateInfo as LegacyTemplateInfo,
)

from .api_message_base import (
    APIMessageBase,
    BaseMessageInfo as APIBaseMessageInfo,
    Seg as APISeg,
    GroupInfo as APIGroupInfo,
    UserInfo as APIUserInfo,
    SenderInfo as APISenderInfo,
    ReceiverInfo as APIReceiverInfo,
    FormatInfo as APIFormatInfo,
    TemplateInfo as APITemplateInfo,
    MessageDim,
)


class MessageConverter:
    """标准化的消息格式转换器
    
    提供 MessageBase 和 APIMessageBase 之间的双向转换。
    必须使用场景化方法进行转换。
    
    场景说明：
    - 接收消息场景 (receive): 外部用户发送消息给 Bot
      → 使用 to_api_receive() 和 from_api_receive()
      → group_info/user_info 与 sender_info 互转（表示消息发送者）
      
    - 发送消息场景 (send): Bot 回复消息给外部用户
      → 使用 to_api_send() 和 from_api_send()
      → group_info/user_info 与 receiver_info 互转（表示消息接收者）
    
    Example:
        # 接收消息时转换（外部用户 -> Bot）
        api_msg = MessageConverter.to_api_receive(legacy_msg, api_key="key")
        legacy_msg = MessageConverter.from_api_receive(api_msg)
        
        # 发送消息时转换（Bot -> 外部用户）
        api_msg = MessageConverter.to_api_send(legacy_msg, api_key="key")
        legacy_msg = MessageConverter.from_api_send(api_msg)
    """

    @staticmethod
    def to_api_receive(
        message: MessageBase,
        api_key: str,
        platform: Optional[str] = None,
    ) -> APIMessageBase:
        """接收场景转换：将 MessageBase 转换为 APIMessageBase
        
        用于处理从外部接收的消息，group_info/user_info 表示消息发送者，
        因此填入 sender_info。
        
        Args:
            message: 要转换的 MessageBase 对象
            api_key: API 密钥
            platform: 可选，平台标识
        
        Returns:
            APIMessageBase: 转换后的消息，sender_info 包含发送者信息
        """
        return MessageConverter._to_api(message, api_key, platform, is_sender=True)

    @staticmethod
    def to_api_send(
        message: MessageBase,
        api_key: str,
        platform: Optional[str] = None,
    ) -> APIMessageBase:
        """发送场景转换：将 MessageBase 转换为 APIMessageBase
        
        用于处理 Bot 发送给外部的消息，group_info/user_info 表示消息接收者，
        因此填入 receiver_info。
        
        Args:
            message: 要转换的 MessageBase 对象
            api_key: API 密钥
            platform: 可选，平台标识
        
        Returns:
            APIMessageBase: 转换后的消息，receiver_info 包含接收者信息
        """
        return MessageConverter._to_api(message, api_key, platform, is_sender=False)

    @staticmethod
    def _to_api(
        message: MessageBase,
        api_key: str,
        platform: Optional[str] = None,
        is_sender: bool = True,
    ) -> APIMessageBase:
        """内部方法：将 MessageBase 转换为 APIMessageBase
        
        请使用 to_api_receive() 或 to_api_send() 代替。
        """
        legacy_info = message.message_info
        legacy_seg = message.message_segment
        
        # 确定 platform
        target_platform = platform or legacy_info.platform or "unknown"
        
        # 构建 MessageDim
        msg_dim = MessageDim(api_key=api_key, platform=target_platform)
        
        # 转换 Seg
        api_seg = APISeg(type=legacy_seg.type, data=legacy_seg.data)
        
        # 提取 group_info 和 user_info
        # 优先使用直接的 group_info/user_info，其次从 sender_info/receiver_info 提取
        group_info, user_info = MessageConverter._extract_group_user_info(legacy_info)
        
        # 构建 API 格式的 GroupInfo 和 UserInfo
        api_group_info = None
        api_user_info = None
        
        if group_info:
            api_group_info = APIGroupInfo(
                platform=group_info.platform or target_platform,
                group_id=str(group_info.group_id) if group_info.group_id else "",
                group_name=group_info.group_name,
            )
        
        if user_info:
            api_user_info = APIUserInfo(
                platform=user_info.platform or target_platform,
                user_id=str(user_info.user_id) if user_info.user_id else "",
                user_nickname=user_info.user_nickname,
                user_cardname=user_info.user_cardname,
            )
        
        # 构建 SenderInfo 或 ReceiverInfo
        sender_info = None
        receiver_info = None
        
        if is_sender:
            if api_group_info or api_user_info:
                sender_info = APISenderInfo(
                    group_info=api_group_info,
                    user_info=api_user_info,
                )
        else:
            if api_group_info or api_user_info:
                receiver_info = APIReceiverInfo(
                    group_info=api_group_info,
                    user_info=api_user_info,
                )
        
        # 转换 FormatInfo
        api_format_info = None
        if legacy_info.format_info:
            api_format_info = APIFormatInfo(
                content_format=legacy_info.format_info.content_format,
                accept_format=legacy_info.format_info.accept_format,
            )
        
        # 转换 TemplateInfo
        api_template_info = None
        if legacy_info.template_info:
            api_template_info = APITemplateInfo(
                template_items=legacy_info.template_info.template_items,
                template_name=legacy_info.template_info.template_name,
                template_default=legacy_info.template_info.template_default,
            )
        
        # 构建 API BaseMessageInfo (API 格式不直接包含 group_info/user_info，只通过 sender_info/receiver_info)
        api_message_info = APIBaseMessageInfo(
            platform=target_platform,
            message_id=str(legacy_info.message_id) if legacy_info.message_id else str(int(time.time() * 1000)),
            time=legacy_info.time or time.time(),
            format_info=api_format_info,
            template_info=api_template_info,
            additional_config=legacy_info.additional_config,
            sender_info=sender_info,
            receiver_info=receiver_info,
        )
        
        return APIMessageBase(
            message_info=api_message_info,
            message_segment=api_seg,
            message_dim=msg_dim,
        )

    @staticmethod
    def from_api_receive(api_message: APIMessageBase) -> MessageBase:
        """接收场景反向转换：将 APIMessageBase 转换为 MessageBase
        
        用于处理从外部接收的消息，从 sender_info 中提取 group_info/user_info
        （因为消息来自外部发送者）。
        
        Args:
            api_message: 要转换的 APIMessageBase 对象
        
        Returns:
            MessageBase: 转换后的消息，group_info/user_info 来自 sender_info
        """
        return MessageConverter._from_api(api_message, source="sender")

    @staticmethod
    def from_api_send(api_message: APIMessageBase) -> MessageBase:
        """发送场景反向转换：将 APIMessageBase 转换为 MessageBase
        
        用于处理 Bot 发送给外部的消息，从 receiver_info 中提取 group_info/user_info
        （因为消息发送给外部接收者）。
        
        Args:
            api_message: 要转换的 APIMessageBase 对象
        
        Returns:
            MessageBase: 转换后的消息，group_info/user_info 来自 receiver_info
        """
        return MessageConverter._from_api(api_message, source="receiver")

    @staticmethod
    def _from_api(
        api_message: APIMessageBase,
        source: str,
    ) -> MessageBase:
        """内部方法：将 APIMessageBase 转换为 MessageBase
        
        请使用 from_api_receive() 或 from_api_send() 代替。
        """
        api_info = api_message.message_info
        api_seg = api_message.message_segment
        
        # 转换 Seg
        legacy_seg = LegacySeg(type=api_seg.type, data=api_seg.data)
        
        # 根据场景提取 group_info 和 user_info
        group_info, user_info = MessageConverter._extract_api_group_user_info(api_info, source)
        
        # 构建 Legacy 格式的 GroupInfo 和 UserInfo
        legacy_group_info = None
        legacy_user_info = None
        
        if group_info:
            legacy_group_info = LegacyGroupInfo(
                platform=group_info.platform,
                group_id=group_info.group_id,
                group_name=group_info.group_name,
            )
        
        if user_info:
            legacy_user_info = LegacyUserInfo(
                platform=user_info.platform,
                user_id=user_info.user_id,
                user_nickname=user_info.user_nickname,
                user_cardname=user_info.user_cardname,
            )
        
        # 构建 SenderInfo 和 ReceiverInfo
        legacy_sender_info = None
        legacy_receiver_info = None
        
        if api_info.sender_info:
            si = api_info.sender_info
            si_group = None
            si_user = None
            if si.group_info:
                si_group = LegacyGroupInfo(
                    platform=si.group_info.platform,
                    group_id=si.group_info.group_id,
                    group_name=si.group_info.group_name,
                )
            if si.user_info:
                si_user = LegacyUserInfo(
                    platform=si.user_info.platform,
                    user_id=si.user_info.user_id,
                    user_nickname=si.user_info.user_nickname,
                    user_cardname=si.user_info.user_cardname,
                )
            legacy_sender_info = LegacySenderInfo(group_info=si_group, user_info=si_user)
        
        if api_info.receiver_info:
            ri = api_info.receiver_info
            ri_group = None
            ri_user = None
            if ri.group_info:
                ri_group = LegacyGroupInfo(
                    platform=ri.group_info.platform,
                    group_id=ri.group_info.group_id,
                    group_name=ri.group_info.group_name,
                )
            if ri.user_info:
                ri_user = LegacyUserInfo(
                    platform=ri.user_info.platform,
                    user_id=ri.user_info.user_id,
                    user_nickname=ri.user_info.user_nickname,
                    user_cardname=ri.user_info.user_cardname,
                )
            legacy_receiver_info = LegacyReceiverInfo(group_info=ri_group, user_info=ri_user)
        
        # 转换 FormatInfo
        legacy_format_info = None
        if api_info.format_info:
            legacy_format_info = LegacyFormatInfo(
                content_format=api_info.format_info.content_format,
                accept_format=api_info.format_info.accept_format,
            )
        
        # 转换 TemplateInfo
        legacy_template_info = None
        if api_info.template_info:
            legacy_template_info = LegacyTemplateInfo(
                template_items=api_info.template_info.template_items,
                template_name=api_info.template_info.template_name,
                template_default=api_info.template_info.template_default,
            )
        
        # 构建 Legacy BaseMessageInfo
        legacy_message_info = LegacyBaseMessageInfo(
            platform=api_info.platform,
            message_id=api_info.message_id,
            time=api_info.time,
            group_info=legacy_group_info,
            user_info=legacy_user_info,
            format_info=legacy_format_info,
            template_info=legacy_template_info,
            additional_config=api_info.additional_config,
            sender_info=legacy_sender_info,
            receiver_info=legacy_receiver_info,
        )
        
        return MessageBase(
            message_info=legacy_message_info,
            message_segment=legacy_seg,
            raw_message=None,
        )

    @staticmethod
    def _extract_group_user_info(legacy_info: LegacyBaseMessageInfo):
        """从 Legacy BaseMessageInfo 中提取 group_info 和 user_info
        
        优先级：
        1. 直接的 group_info/user_info 字段
        2. sender_info 中的 group_info/user_info
        3. receiver_info 中的 group_info/user_info
        """
        group_info = None
        user_info = None
        
        # 优先使用直接字段
        if legacy_info.group_info:
            group_info = legacy_info.group_info
        if legacy_info.user_info:
            user_info = legacy_info.user_info
        
        # 从 sender_info 提取
        if legacy_info.sender_info:
            if not group_info and legacy_info.sender_info.group_info:
                group_info = legacy_info.sender_info.group_info
            if not user_info and legacy_info.sender_info.user_info:
                user_info = legacy_info.sender_info.user_info
        
        # 从 receiver_info 提取
        if legacy_info.receiver_info:
            if not group_info and legacy_info.receiver_info.group_info:
                group_info = legacy_info.receiver_info.group_info
            if not user_info and legacy_info.receiver_info.user_info:
                user_info = legacy_info.receiver_info.user_info
        
        return group_info, user_info

    @staticmethod
    def _extract_api_group_user_info(
        api_info: APIBaseMessageInfo,
        source: Optional[str] = None,
    ):
        """从 API BaseMessageInfo 中提取 group_info 和 user_info
        
        API 格式只通过 sender_info/receiver_info 来包含用户和群组信息，
        此方法根据场景从指定结构中提取。
        
        Args:
            api_info: API 格式的 BaseMessageInfo
            source: 指定从哪里提取
                   - "sender": 只从 sender_info 提取
                   - "receiver": 只从 receiver_info 提取
                   - None: 自动检测（先 sender_info，后 receiver_info）
        
        Returns:
            tuple: (group_info, user_info)
        """
        group_info = None
        user_info = None
        
        if source == "sender":
            # 只从 sender_info 提取
            if api_info.sender_info:
                group_info = api_info.sender_info.group_info
                user_info = api_info.sender_info.user_info
        elif source == "receiver":
            # 只从 receiver_info 提取
            if api_info.receiver_info:
                group_info = api_info.receiver_info.group_info
                user_info = api_info.receiver_info.user_info
        else:
            # 自动检测：先 sender_info，后 receiver_info
            if api_info.sender_info:
                if api_info.sender_info.group_info:
                    group_info = api_info.sender_info.group_info
                if api_info.sender_info.user_info:
                    user_info = api_info.sender_info.user_info
            
            if api_info.receiver_info:
                if not group_info and api_info.receiver_info.group_info:
                    group_info = api_info.receiver_info.group_info
                if not user_info and api_info.receiver_info.user_info:
                    user_info = api_info.receiver_info.user_info
        
        return group_info, user_info
