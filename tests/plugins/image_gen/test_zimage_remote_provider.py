#!/usr/bin/env python3
"""Tests for the remote Z-Image worker image generation provider."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_zimage_env(monkeypatch):
    for key in (
        "ZIMAGE_REMOTE_BASE_URL",
        "ZIMAGE_REMOTE_TOKEN",
        "ZIMAGE_REMOTE_MODEL",
        "ZIMAGE_REMOTE_TIMEOUT_SECONDS",
        "ZIMAGE_REMOTE_POLL_TIMEOUT_SECONDS",
        "ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS",
        "ZIMAGE_REMOTE_TRANSPORT",
        "ZIMAGE_REMOTE_SYSTEM_PYTHON",
        "ZIMAGE_REMOTE_ROUTE_RETRY_ATTEMPTS",
        "ZIMAGE_REMOTE_ROUTE_RETRY_DELAY_SECONDS",
        "ZIMAGE_REMOTE_DISABLED",
    ):
        monkeypatch.delenv(key, raising=False)


class TestZImageRemoteProvider:
    def test_provider_metadata_and_setup_schema(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        provider = ZImageRemoteProvider()
        assert provider.name == "zimage_remote"
        assert provider.display_name == "Z-Image Remote"
        assert provider.is_available() is True
        assert provider.default_model() == "Tongyi-MAI/Z-Image-Turbo"
        assert provider.list_models()[0]["id"] == "Tongyi-MAI/Z-Image-Turbo"

        schema = provider.get_setup_schema()
        assert schema["name"] == "Z-Image Remote"
        assert schema["badge"] == "local-gpu"
        assert {item["key"] for item in schema["env_vars"]} == {
            "ZIMAGE_REMOTE_BASE_URL",
            "ZIMAGE_REMOTE_TOKEN",
        }

    def test_unavailable_without_base_url(self):
        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        provider = ZImageRemoteProvider()
        assert provider.is_available() is False
        result = provider.generate(prompt="a portrait")
        assert result["success"] is False
        assert result["error_type"] == "configuration_required"
        assert "ZIMAGE_REMOTE_BASE_URL" in result["error"]

    def test_disabled_kill_switch_overrides_base_url(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_DISABLED", "1")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        provider = ZImageRemoteProvider()
        assert provider.is_available() is False
        with patch("plugins.image_gen.zimage_remote.requests.post") as mock_post:
            result = provider.generate(prompt="a portrait")

        assert result["success"] is False
        assert result["error_type"] == "provider_disabled"
        assert "disabled" in result["error"].lower()
        mock_post.assert_not_called()

    def test_disabled_kill_switch_skips_provider_registration(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_DISABLED", "1")

        from plugins.image_gen.zimage_remote import register

        ctx = MagicMock()
        register(ctx)

        ctx.register_image_gen_provider.assert_not_called()

    def test_reference_images_are_explicitly_unsupported(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        with patch("plugins.image_gen.zimage_remote.requests.post") as mock_post:
            result = ZImageRemoteProvider().generate(
                prompt="preserve this source identity",
                reference_images=["/tmp/source.png"],
            )

        assert result["success"] is False
        assert result["error_type"] == "unsupported_feature"
        assert "reference_images" in result["error"]
        assert result["reference_conditioning"] == "unsupported"
        mock_post.assert_not_called()

    def test_success_posts_worker_payload_and_caches_remote_url(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test/api")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "success": True,
            "image_url": "https://zimage-worker.test/files/out.png",
            "seed": 12345,
            "model": "Tongyi-MAI/Z-Image-Turbo",
            "model_revision": "abc123",
            "elapsed_ms": 1840,
            "vram_peak_mb": 14200,
            "worker_id": "gpu-box-1",
            "job_id": "job-1",
        }

        with patch("plugins.image_gen.zimage_remote.requests.post", return_value=response) as mock_post, \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_requests",
                 return_value=Path("/tmp/zimage_remote.png"),
             ) as mock_save:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="portrait",
                seed=12345,
                num_inference_steps=9,
                guidance_scale=0.0,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_remote.png"
        assert result["provider"] == "zimage_remote"
        assert result["model"] == "Tongyi-MAI/Z-Image-Turbo"
        assert result["seed"] == 12345
        assert result["model_revision"] == "abc123"
        assert result["elapsed_ms"] == 1840
        assert result["vram_peak_mb"] == 14200
        assert result["worker_id"] == "gpu-box-1"
        assert result["job_id"] == "job-1"
        assert result["reference_conditioning"] == "none"
        assert result["generation_metadata"] == {
            "remote_image": "https://zimage-worker.test/files/out.png",
            "model_revision": "abc123",
            "elapsed_ms": 1840,
            "vram_peak_mb": 14200,
            "worker_id": "gpu-box-1",
            "job_id": "job-1",
            "reference_conditioning": "none",
        }

        mock_save.assert_called_once_with(
            "https://zimage-worker.test/files/out.png",
            prefix="zimage_remote_Tongyi-MAI_Z-Image-Turbo",
            headers={"Accept": "image/*", "Authorization": "Bearer secret-token"},
        )
        url = mock_post.call_args[0][0]
        headers = mock_post.call_args.kwargs["headers"]
        payload = mock_post.call_args.kwargs["json"]
        assert url == "https://zimage-worker.test/api/txt2img"
        assert headers["Authorization"] == "Bearer secret-token"
        assert payload["prompt"] == "cinematic photobook portrait"
        assert payload["aspect_ratio"] == "portrait"
        assert payload["width"] == 576
        assert payload["height"] == 1024
        assert payload["num_inference_steps"] == 9
        assert payload["guidance_scale"] == 0.0
        assert payload["seed"] == 12345

    def test_async_job_contract_polls_result_and_downloads_file_url(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "http://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")
        monkeypatch.setenv("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS", "0")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        submit = MagicMock()
        submit.status_code = 200
        submit.json.return_value = {
            "job_id": "job-123",
            "poll_url": "/jobs/job-123",
            "status": "queued",
            "worker_id": "remote-rtx5080-01",
        }

        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = {
            "job_id": "job-123",
            "status": "succeeded",
            "result": {
                "image_id": "2026/06/12/job-123.png",
                "file_url": "/files/2026%2F06%2F12%2Fjob-123.png",
                "seed": 5678,
                "model_id": "Tongyi-MAI/Z-Image-Turbo",
                "model_revision": "main",
                "elapsed_ms": 107424,
                "vram_peak_mb": 12334,
                "reference_conditioning": "none",
            },
        }

        with patch("plugins.image_gen.zimage_remote.requests.post", return_value=submit) as mock_post, \
             patch("plugins.image_gen.zimage_remote.requests.get", return_value=poll) as mock_get, \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_requests",
                 return_value=Path("/tmp/zimage_async.png"),
             ) as mock_save:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="square",
                seed=5678,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_async.png"
        assert result["seed"] == 5678
        assert result["model"] == "Tongyi-MAI/Z-Image-Turbo"
        assert result["model_revision"] == "main"
        assert result["elapsed_ms"] == 107424
        assert result["vram_peak_mb"] == 12334
        assert result["worker_id"] == "remote-rtx5080-01"
        assert result["job_id"] == "job-123"
        assert result["generation_metadata"] == {
            "remote_image": "http://zimage-worker.test/files/2026%2F06%2F12%2Fjob-123.png",
            "model_revision": "main",
            "elapsed_ms": 107424,
            "vram_peak_mb": 12334,
            "worker_id": "remote-rtx5080-01",
            "job_id": "job-123",
            "reference_conditioning": "none",
        }

        assert mock_post.call_args[0][0] == "http://zimage-worker.test/txt2img"
        assert mock_get.call_args[0][0] == "http://zimage-worker.test/jobs/job-123"
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-token"
        mock_save.assert_called_once_with(
            "http://zimage-worker.test/files/2026%2F06%2F12%2Fjob-123.png",
            prefix="zimage_remote_Tongyi-MAI_Z-Image-Turbo",
            headers={"Accept": "image/*", "Authorization": "Bearer secret-token"},
        )

    def test_auto_transport_uses_system_python_for_local_route_block(self, monkeypatch):
        import requests as req_lib

        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "http://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")
        monkeypatch.setenv("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS", "0")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        submit = MagicMock()
        submit.status_code = 200
        submit.json.return_value = {
            "job_id": "job-system-auto",
            "poll_url": "/jobs/job-system-auto",
            "status": "queued",
            "worker_id": "remote-rtx5080-01",
        }

        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = {
            "job_id": "job-system-auto",
            "status": "succeeded",
            "result": {
                "file_url": "/files/job-system-auto.png",
                "seed": 6789,
                "model_id": "Tongyi-MAI/Z-Image-Turbo",
                "model_revision": "main",
                "elapsed_ms": 27192,
                "vram_peak_mb": 12334,
                "reference_conditioning": "none",
            },
        }

        route_block = req_lib.ConnectionError("[Errno 65] No route to host")
        with patch("plugins.image_gen.zimage_remote.requests.post", side_effect=route_block), \
             patch("plugins.image_gen.zimage_remote.requests.get", side_effect=route_block), \
             patch(
                 "plugins.image_gen.zimage_remote._system_python_json_request",
                 side_effect=[submit, poll],
             ) as mock_system_json, \
             patch(
                 "plugins.image_gen.zimage_remote._curl_json_request",
             ) as mock_curl_json, \
             patch("plugins.image_gen.zimage_remote._save_url_image_with_requests", side_effect=route_block), \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_system_python",
                 return_value=Path("/tmp/zimage_system_auto.png"),
             ) as mock_system_save:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="square",
                seed=6789,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_system_auto.png"
        assert result["job_id"] == "job-system-auto"
        assert result["seed"] == 6789
        assert result["generation_metadata"]["remote_image"] == "http://zimage-worker.test/files/job-system-auto.png"
        assert mock_system_json.call_args_list[0].args[:2] == ("POST", "http://zimage-worker.test/txt2img")
        assert mock_system_json.call_args_list[1].args[:2] == ("GET", "http://zimage-worker.test/jobs/job-system-auto")
        mock_curl_json.assert_not_called()
        mock_system_save.assert_called_once_with(
            "http://zimage-worker.test/files/job-system-auto.png",
            prefix="zimage_remote_Tongyi-MAI_Z-Image-Turbo",
            headers={"Accept": "image/*", "Authorization": "Bearer secret-token"},
        )

    def test_auto_transport_falls_back_to_curl_when_system_python_fails(self, monkeypatch):
        import requests as req_lib

        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "http://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")
        monkeypatch.setenv("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS", "0")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider, _RemoteTransportError

        submit = MagicMock()
        submit.status_code = 200
        submit.json.return_value = {
            "job_id": "job-curl",
            "poll_url": "/jobs/job-curl",
            "status": "queued",
            "worker_id": "remote-rtx5080-01",
        }

        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = {
            "job_id": "job-curl",
            "status": "succeeded",
            "result": {
                "file_url": "/files/job-curl.png",
                "seed": 6790,
                "model_id": "Tongyi-MAI/Z-Image-Turbo",
                "model_revision": "main",
                "elapsed_ms": 27192,
                "vram_peak_mb": 12334,
                "reference_conditioning": "none",
            },
        }

        route_block = req_lib.ConnectionError("[Errno 65] No route to host")
        system_down = _RemoteTransportError("system-python transport failed")
        with patch("plugins.image_gen.zimage_remote.requests.post", side_effect=route_block), \
             patch("plugins.image_gen.zimage_remote.requests.get", side_effect=route_block), \
             patch(
                 "plugins.image_gen.zimage_remote._system_python_json_request",
                 side_effect=[system_down, system_down],
             ) as mock_system_json, \
             patch(
                 "plugins.image_gen.zimage_remote._curl_json_request",
                 side_effect=[submit, poll],
             ) as mock_curl_json, \
             patch("plugins.image_gen.zimage_remote._save_url_image_with_requests", side_effect=route_block), \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_system_python",
                 side_effect=system_down,
             ) as mock_system_save, \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_curl",
                 return_value=Path("/tmp/zimage_curl.png"),
             ) as mock_curl_save:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="square",
                seed=6790,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_curl.png"
        assert result["job_id"] == "job-curl"
        assert result["seed"] == 6790
        assert result["generation_metadata"]["remote_image"] == "http://zimage-worker.test/files/job-curl.png"
        assert len(mock_system_json.call_args_list) == 2
        assert mock_curl_json.call_args_list[0].args[:2] == ("POST", "http://zimage-worker.test/txt2img")
        assert mock_curl_json.call_args_list[1].args[:2] == ("GET", "http://zimage-worker.test/jobs/job-curl")
        mock_system_save.assert_called_once()
        mock_curl_save.assert_called_once_with(
            "http://zimage-worker.test/files/job-curl.png",
            prefix="zimage_remote_Tongyi-MAI_Z-Image-Turbo",
            headers={"Accept": "image/*", "Authorization": "Bearer secret-token"},
        )

    def test_system_python_transport_submit_poll_and_download(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "http://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")
        monkeypatch.setenv("ZIMAGE_REMOTE_TRANSPORT", "system-python")
        monkeypatch.setenv("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS", "0")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        submit = MagicMock()
        submit.status_code = 200
        submit.json.return_value = {
            "job_id": "job-system",
            "poll_url": "/jobs/job-system",
            "status": "queued",
            "worker_id": "remote-rtx5080-01",
        }

        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = {
            "job_id": "job-system",
            "status": "succeeded",
            "result": {
                "file_url": "/files/job-system.png",
                "seed": 2468,
                "model_id": "Tongyi-MAI/Z-Image-Turbo",
                "model_revision": "main",
                "elapsed_ms": 12345,
                "vram_peak_mb": 12000,
                "reference_conditioning": "none",
            },
        }

        with patch("plugins.image_gen.zimage_remote.requests.post") as mock_post, \
             patch("plugins.image_gen.zimage_remote.requests.get") as mock_get, \
             patch("plugins.image_gen.zimage_remote._curl_json_request") as mock_curl_json, \
             patch(
                 "plugins.image_gen.zimage_remote._system_python_json_request",
                 side_effect=[submit, poll],
             ) as mock_system_json, \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_system_python",
                 return_value=Path("/tmp/zimage_system.png"),
             ) as mock_system_save:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="square",
                seed=2468,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_system.png"
        assert result["job_id"] == "job-system"
        assert result["seed"] == 2468
        assert result["generation_metadata"]["remote_image"] == "http://zimage-worker.test/files/job-system.png"
        mock_post.assert_not_called()
        mock_get.assert_not_called()
        mock_curl_json.assert_not_called()
        assert mock_system_json.call_args_list[0].args[:2] == ("POST", "http://zimage-worker.test/txt2img")
        assert mock_system_json.call_args_list[1].args[:2] == ("GET", "http://zimage-worker.test/jobs/job-system")
        mock_system_save.assert_called_once_with(
            "http://zimage-worker.test/files/job-system.png",
            prefix="zimage_remote_Tongyi-MAI_Z-Image-Turbo",
            headers={"Accept": "image/*", "Authorization": "Bearer secret-token"},
        )

    def test_system_python_transport_retries_transient_route_block(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "http://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")
        monkeypatch.setenv("ZIMAGE_REMOTE_TRANSPORT", "system-python")
        monkeypatch.setenv("ZIMAGE_REMOTE_ROUTE_RETRY_ATTEMPTS", "3")
        monkeypatch.setenv("ZIMAGE_REMOTE_ROUTE_RETRY_DELAY_SECONDS", "0")
        monkeypatch.setenv("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS", "0")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider, _RemoteTransportError

        submit = MagicMock()
        submit.status_code = 200
        submit.json.return_value = {
            "job_id": "job-route-retry",
            "poll_url": "/jobs/job-route-retry",
            "status": "queued",
            "worker_id": "remote-rtx5080-01",
        }

        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = {
            "job_id": "job-route-retry",
            "status": "succeeded",
            "result": {
                "file_url": "/files/job-route-retry.png",
                "seed": 2469,
                "model_id": "Tongyi-MAI/Z-Image-Turbo",
                "model_revision": "main",
                "reference_conditioning": "none",
            },
        }
        transient = _RemoteTransportError(
            "system-python transport failed (1): <urlopen error [Errno 65] No route to host>"
        )

        with patch("plugins.image_gen.zimage_remote._system_python_json_request", side_effect=[transient, submit, poll]) as mock_system_json, \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_system_python",
                 return_value=Path("/tmp/zimage_route_retry.png"),
             ), \
             patch("plugins.image_gen.zimage_remote.time.sleep") as mock_sleep:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="square",
                seed=2469,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_route_retry.png"
        assert result["job_id"] == "job-route-retry"
        assert len(mock_system_json.call_args_list) == 3
        mock_sleep.assert_called_once_with(0.0)

    def test_system_python_download_retries_transient_route_block(self, monkeypatch):
        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "http://zimage-worker.test")
        monkeypatch.setenv("ZIMAGE_REMOTE_TOKEN", "secret-token")
        monkeypatch.setenv("ZIMAGE_REMOTE_TRANSPORT", "system-python")
        monkeypatch.setenv("ZIMAGE_REMOTE_ROUTE_RETRY_ATTEMPTS", "3")
        monkeypatch.setenv("ZIMAGE_REMOTE_ROUTE_RETRY_DELAY_SECONDS", "0")
        monkeypatch.setenv("ZIMAGE_REMOTE_POLL_INTERVAL_SECONDS", "0")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider, _RemoteTransportError

        submit = MagicMock()
        submit.status_code = 200
        submit.json.return_value = {
            "job_id": "job-download-retry",
            "poll_url": "/jobs/job-download-retry",
            "status": "queued",
        }

        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = {
            "job_id": "job-download-retry",
            "status": "succeeded",
            "result": {
                "file_url": "/files/job-download-retry.png",
                "seed": 2470,
                "model_id": "Tongyi-MAI/Z-Image-Turbo",
                "model_revision": "main",
                "reference_conditioning": "none",
            },
        }
        transient = _RemoteTransportError(
            "system-python image download failed (1): <urlopen error [Errno 65] No route to host>"
        )

        with patch("plugins.image_gen.zimage_remote._system_python_json_request", side_effect=[submit, poll]), \
             patch(
                 "plugins.image_gen.zimage_remote._save_url_image_with_system_python",
                 side_effect=[transient, Path("/tmp/zimage_download_retry.png")],
             ) as mock_system_save, \
             patch("plugins.image_gen.zimage_remote.time.sleep") as mock_sleep:
            result = ZImageRemoteProvider().generate(
                prompt="cinematic photobook portrait",
                aspect_ratio="square",
                seed=2470,
            )

        assert result["success"] is True
        assert result["image"] == "/tmp/zimage_download_retry.png"
        assert result["job_id"] == "job-download-retry"
        assert len(mock_system_save.call_args_list) == 2
        mock_sleep.assert_called_once_with(0.0)

    def test_worker_api_error_is_structured(self, monkeypatch):
        import requests as req_lib

        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        response = req_lib.Response()
        response.status_code = 503
        response._content = b'{"error": "model is still loading"}'
        response.headers["Content-Type"] = "application/json"

        with patch("plugins.image_gen.zimage_remote.requests.post", return_value=response):
            result = ZImageRemoteProvider().generate(prompt="cinematic portrait")

        assert result["success"] is False
        assert result["error_type"] == "remote_worker_error"
        assert "model is still loading" in result["error"]
        assert result["status_code"] == 503

    def test_worker_error_type_is_preserved(self, monkeypatch):
        import requests as req_lib

        monkeypatch.setenv("ZIMAGE_REMOTE_BASE_URL", "https://zimage-worker.test")

        from plugins.image_gen.zimage_remote import ZImageRemoteProvider

        response = req_lib.Response()
        response.status_code = 422
        response._content = b'{"error": "reference_images unsupported", "error_type": "unsupported_feature"}'
        response.headers["Content-Type"] = "application/json"

        with patch("plugins.image_gen.zimage_remote.requests.post", return_value=response):
            result = ZImageRemoteProvider().generate(prompt="cinematic portrait")

        assert result["success"] is False
        assert result["error_type"] == "unsupported_feature"
        assert "reference_images unsupported" in result["error"]
        assert result["status_code"] == 422

    def test_register_wires_provider(self):
        from plugins.image_gen.zimage_remote import ZImageRemoteProvider, register

        ctx = MagicMock()
        register(ctx)

        ctx.register_image_gen_provider.assert_called_once()
        provider = ctx.register_image_gen_provider.call_args[0][0]
        assert isinstance(provider, ZImageRemoteProvider)
