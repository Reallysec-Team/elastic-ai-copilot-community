"""渠道错误的共同基类。

outbox 只关心两件事：这次为什么失败、值不值得重试。四个渠道各有各的失败方式
（飞书的 code、钉钉的 errcode、SMTP 的响应码），但对队列而言它们是同一件事，所以
共用一个基类，outbox 捕一次就够 —— 每加一个渠道就往 except 元组里塞一个类，是那种
迟早会漏掉一个的写法。

``retryable`` 的判据统一是：**重试有没有可能成功**。连不上、超时、限流 → 有；
签名错、地址错、认证失败 → 没有，重试一百次也是错，直接进死信让人来看。
"""

from __future__ import annotations


class ChannelError(Exception):
    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable
