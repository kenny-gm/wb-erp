"""
Wildberries 客服 API 客户端

封装 Customer Communication 相关接口：
- Questions / Feedbacks
- Buyers chat
- Buyers returns

注意：不要在本模块持久化 token。调用方每次从 Shop.api_token 创建客户端。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

import httpx


class WBCustomerRateLimit(Exception):
    """WB 客服 API 限流"""


class WBCustomerAPIError(Exception):
    """WB 客服 API 错误"""

    def __init__(self, message: str, status_code: Optional[int] = None, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class WBCustomerClient:
    FEEDBACKS_API = "https://feedbacks-api.wildberries.ru"
    BUYER_CHAT_API = "https://buyer-chat-api.wildberries.ru"
    RETURNS_API = "https://returns-api.wildberries.ru"

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.headers = {
            "Authorization": api_token,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        base_url: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry: int = 1,
    ) -> Any:
        url = f"{base_url}{endpoint}"
        last_error: Optional[Exception] = None

        for attempt in range(retry + 1):
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.request(
                        method,
                        url,
                        headers=self.headers,
                        params=params,
                        json=json_data,
                    )

                if response.status_code in (200, 201):
                    if not response.content:
                        return {}
                    return response.json()
                if response.status_code == 204:
                    return {}
                if response.status_code == 202:
                    return {"status": "pending", "detail": response.text}
                if response.status_code == 420 or response.status_code == 429:
                    raise WBCustomerRateLimit(response.text[:500])
                if response.status_code == 401:
                    raise WBCustomerAPIError(
                        "WB API token 无效或已过期",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                if response.status_code == 403:
                    raise WBCustomerAPIError(
                        f"WB API 权限不足: {response.text[:500]}",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )

                raise WBCustomerAPIError(
                    f"WB API 请求失败 [{response.status_code}]: {response.text[:500]}",
                    status_code=response.status_code,
                    response_text=response.text[:500],
                )
            except WBCustomerRateLimit:
                raise
            except WBCustomerAPIError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < retry:
                    time.sleep(2)
                    continue
                raise WBCustomerAPIError(str(last_error))

        raise WBCustomerAPIError(str(last_error or "WB API 请求失败"))

    # ========== Questions ==========

    def get_questions(
        self,
        is_answered: Optional[bool] = None,
        take: int = 100,
        skip: int = 0,
        date_from: Optional[int] = None,
        date_to: Optional[int] = None,
        nm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"take": take, "skip": skip, "order": "dateDesc"}
        if is_answered is not None:
            params["isAnswered"] = str(is_answered).lower()
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        if nm_id is not None:
            params["nmId"] = nm_id
        return self._request("GET", self.FEEDBACKS_API, "/api/v1/questions", params=params)

    def get_question(self, question_id: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            self.FEEDBACKS_API,
            "/api/v1/question",
            params={"id": question_id},
        )

    def answer_question(self, question_id: str, text: str, visibility_type: str = "all") -> Dict[str, Any]:
        """
        回复买家问答
        visibility_type: "all" - 所有人可见, "questioner" - 仅提问者可见
        """
        return self._request(
            "PATCH",
            self.FEEDBACKS_API,
            "/api/v1/questions",
            json_data={"id": question_id, "answer": {"text": text, "visibilityType": visibility_type}},
        )

    def reject_question(self, question_id: str) -> Dict[str, Any]:
        """拒绝问题（关闭）"""
        return self._request(
            "PATCH",
            self.FEEDBACKS_API,
            "/api/v1/questions",
            json_data={"id": question_id, "status": "rejected"},
        )

    def edit_question_answer(self, question_id: str, text: str, visibility_type: str = "all") -> Dict[str, Any]:
        """修改已回答的问题答案（同时可更新可见范围）"""
        return self._request(
            "PATCH",
            self.FEEDBACKS_API,
            "/api/v1/questions",
            json_data={"id": question_id, "answer": {"text": text, "visibilityType": visibility_type}},
        )

    # ========== Feedbacks ==========

    def get_feedbacks(
        self,
        is_answered: Optional[bool] = None,
        take: int = 100,
        skip: int = 0,
        date_from: Optional[int] = None,
        date_to: Optional[int] = None,
        nm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"take": take, "skip": skip, "order": "dateDesc"}
        if is_answered is not None:
            params["isAnswered"] = str(is_answered).lower()
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        if nm_id is not None:
            params["nmId"] = nm_id
        return self._request("GET", self.FEEDBACKS_API, "/api/v1/feedbacks", params=params)

    def get_feedback(self, feedback_id: str) -> Dict[str, Any]:
        return self._request(
            "GET",
            self.FEEDBACKS_API,
            "/api/v1/feedback",
            params={"id": feedback_id},
        )

    def answer_feedback(self, feedback_id: str, text: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            self.FEEDBACKS_API,
            "/api/v1/feedbacks/answer",
            json_data={"id": feedback_id, "text": text},
        )

    def edit_feedback_answer(self, feedback_id: str, text: str) -> Dict[str, Any]:
        return self._request(
            "PATCH",
            self.FEEDBACKS_API,
            "/api/v1/feedbacks/answer",
            json_data={"id": feedback_id, "text": text},
        )

    # ========== Buyers chat ==========

    def get_chats(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return self._request(
            "GET",
            self.BUYER_CHAT_API,
            "/api/v1/seller/chats",
            params={"limit": limit, "offset": offset},
        )

    def get_chat_events(
        self,
        next_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """WB 买家聊天事件流。首次请求不带 next，后续请求带 next。"""
        params: Dict[str, Any] = {}
        if next_cursor:
            params["next"] = next_cursor
        return self._request(
            "GET",
            self.BUYER_CHAT_API,
            "/api/v1/seller/events",
            params=params,
        )

    def send_chat_message(
        self,
        reply_sign: str,
        message: str,
        file_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"replySign": reply_sign, "message": message}
        if file_ids:
            payload["fileIds"] = list(file_ids)
        return self._request(
            "POST",
            self.BUYER_CHAT_API,
            "/api/v1/seller/message",
            json_data=payload,
        )

    def download_url(self, download_id: str) -> str:
        return f"{self.BUYER_CHAT_API}/api/v1/seller/download/{download_id}"

    # ========== Buyers returns ==========

    def get_return_claims(
        self,
        limit: int = 100,
        offset: int = 0,
        is_archive: bool = False,
        nm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "is_archive": str(is_archive).lower(),
        }
        if nm_id is not None:
            params["nm_id"] = nm_id
        return self._request("GET", self.RETURNS_API, "/api/v1/claims", params=params)

    def answer_return_claim(
        self,
        claim_id: str,
        action: str,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": claim_id, "action": action}
        if comment:
            payload["comment"] = comment
        return self._request("PATCH", self.RETURNS_API, "/api/v1/claim", json_data=payload)

    # ========== Permission check ==========

    def check_permissions(self) -> Dict[str, Dict[str, Any]]:
        checks = {
            "feedbacks_questions": lambda: self.get_questions(take=1, skip=0),
            "buyers_chat_list": lambda: self.get_chats(limit=1, offset=0),
            "buyers_chat_events": lambda: self.get_chat_events(),
            "buyers_returns": lambda: self.get_return_claims(limit=1, offset=0),
        }

        result: Dict[str, Dict[str, Any]] = {}
        for key, fn in checks.items():
            try:
                fn()
                result[key] = {"available": True, "error": ""}
            except WBCustomerRateLimit as exc:
                result[key] = {"available": False, "rate_limited": True, "error": str(exc)}
            except Exception as exc:
                result[key] = {"available": False, "error": str(exc)}
        return result
