"""End-to-end integration and codec test for Google Flow batchexecute RPC."""

import os
import sys
import unittest
from typing import Dict, Any

# Ensure current directory is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from flow_batch import (
    RPC_CREDITS, RPC_GEN_IMAGE, RPC_GEN_VIDEO, RPC_MEDIA, RPC_UPLOAD_IMAGE, RPC_OPERATION,
    credits_request, image_request, video_request, upload_request, operation_request, media_request,
    first_payload, read_credits, read_images, read_video_media_id, read_media_urls, read_uploaded_media_id,
    resolve_video_model, resolve_image_model, resolve_aspect, resolve_video_aspect
)
from complete_flow import LabsFlowClient


class TestFlowBatchIntegration(unittest.TestCase):
    def test_codec_credits(self):
        req = credits_request()
        self.assertIn("nzlxg", req)
        mock_raw = ')]}\'\n121\n[["wrb.fr","nzlxg","[46,2,3,3,null,46]",null,null,null,"generic"],["di",382],["af.httprm",381,"898425150956824596",37]]'
        pay = first_payload(mock_raw, RPC_CREDITS)
        info = read_credits(pay)
        self.assertIsNotNone(info)
        self.assertEqual(info.remaining, 46)
        self.assertEqual(info.tier, "TIER_2")
        # Test tuple unpacking
        rem, tier = read_credits(pay)
        self.assertEqual(rem, 46)
        self.assertEqual(tier, "TIER_2")

    def test_codec_image(self):
        req = image_request(
            prompt="A cinematic neon cyberpunk street, rain reflections, 8k",
            project_id="test-proj-123",
            count=2,
            aspect="16:9"
        )
        self.assertIn("ogiZ0b", req)
        self.assertIn("test-proj-123", req)

        mock_raw = ')]}\'\n100\n[["wrb.fr","ogiZ0b","[[null,[[\\\"https://flow-content.google/image/img-111\\\",null,\\\"img-111\\\"]]]]",null,null,null,"generic"]]'
        pay = first_payload(mock_raw, RPC_GEN_IMAGE)
        imgs = read_images(pay)
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0].media_id, "img-111")
        self.assertEqual(imgs[0].url, "https://flow-content.google/image/img-111")

    def test_codec_video(self):
        req = video_request(
            prompt="A majestic eagle soaring over foggy mountains",
            project_id="test-proj-123",
            source_media_id="img-111",
            aspect="9:16",
            model="veo_3_1_t2v_lite_4s"
        )
        self.assertIn("eb1hJf", req)
        self.assertIn("img-111", req)

        mock_raw = ')]}\'\n100\n[["wrb.fr","eb1hJf","[null,null,\\\"2caaf06c-48be-4cb0-9426-38ef2f0592ca\\\",\\\"ebe419df-5136-41bf-a81d-b65747ea015b\\\"]",null,null,null,"generic"]]'
        pay = first_payload(mock_raw, RPC_GEN_VIDEO)
        media_id, op_id = read_video_media_id(pay)
        self.assertEqual(media_id, "2caaf06c-48be-4cb0-9426-38ef2f0592ca")
        self.assertEqual(op_id, "ebe419df-5136-41bf-a81d-b65747ea015b")

    def test_codec_media_urls(self):
        req = media_request("media-vid-999")
        self.assertIn("as29s", req)
        mock_raw = ')]}\'\n100\n[["wrb.fr","as29s","[[null,\\\"https://flow-content.google/video/stream.mp4\\\"]]",null,null,null,"generic"]]'
        pay = first_payload(mock_raw, RPC_MEDIA)
        urls = read_media_urls(pay, "media-vid-999")
        self.assertEqual(urls.media_id, "media-vid-999")
        self.assertEqual(urls.video, "https://flow-content.google/video/stream.mp4")

    def test_client_initialization_and_batch_rpc(self):
        dummy_cookies = {"SID": "test-sid", "__Secure-1PSID": "test-psid"}
        client = LabsFlowClient(dummy_cookies)
        self.assertEqual(client.cookies["SID"], "test-sid")
        self.assertTrue(hasattr(client, "batch_rpc"))

        # Test batch_rpc without bridge running or with offline bridge -> should return gracefully
        res = client.batch_rpc(RPC_CREDITS, credits_request(), timeout=1)
        self.assertIsInstance(res, dict)
        self.assertIn("ok", res)

    def test_cookie_credits_rpc_success(self):
        from unittest.mock import patch
        from gui_app_mac import GoogleLabsFlowQt6
        
        mock_raw = ')]}\'\n121\n[["wrb.fr","nzlxg","[46,2,3,3,null,46]",null,null,null,"generic"]]'
        with patch.object(LabsFlowClient, "batch_rpc", return_value={"ok": True, "data": mock_raw}):
            dummy_app = GoogleLabsFlowQt6.__new__(GoogleLabsFlowQt6)
            dummy_app.log = lambda msg: None
            
            ok, data, msg = GoogleLabsFlowQt6.check_cookie_credits(dummy_app, "SID=abc; __Secure-1PSID=xyz;")
            self.assertTrue(ok)
            self.assertEqual(data.get("credits"), 46)
            self.assertEqual(data.get("userPaygateTier"), "TIER_2")
            
            is_live, live_msg = GoogleLabsFlowQt6.check_cookie_live(dummy_app, "SID=abc; __Secure-1PSID=xyz;")
            self.assertTrue(is_live)
            self.assertIn("Credits: 46", live_msg)


if __name__ == "__main__":
    unittest.main()
