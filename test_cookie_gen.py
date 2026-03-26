import json
from complete_flow import LabsFlowClient

# The user-provided cookie
cookie_json = """
[
    {
        "domain": "labs.google",
        "hostOnly": true,
        "httpOnly": true,
        "name": "__Host-next-auth.csrf-token",
        "path": "/",
        "sameSite": "lax",
        "secure": true,
        "session": true,
        "storeId": null,
        "value": "0249be10da7189556ce209f142e144634bd14b4cb06eee64c2b7977191772af7%7Cdb44dc206d2703c11ef24d046fe578b0fc01d17810c5555d180f8c2e1ae205a9"
    },
    {
        "domain": "labs.google",
        "hostOnly": true,
        "httpOnly": true,
        "name": "__Secure-next-auth.callback-url",
        "path": "/",
        "sameSite": "lax",
        "secure": true,
        "session": true,
        "storeId": null,
        "value": "https%3A%2F%2Flabs.google"
    },
    {
        "domain": "labs.google",
        "expirationDate": 1777034447.749984,
        "hostOnly": true,
        "httpOnly": true,
        "name": "__Secure-next-auth.session-token",
        "path": "/",
        "sameSite": "lax",
        "secure": true,
        "session": false,
        "storeId": null,
        "value": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..FBz7-FL9177ByZjl.G1J9B8oaHsaf9ggeZskpi2zUnta_PUBZNadveHzP211rINVoaEZmx39YYmxBqrACpZ4itdHQz092DsezB6k3o5li3EolYx3Mncs2FAF-sG24WBM9S7DkjsSqlWgesc5KxEfCeHQRf6PsDchoPrOeYlKCjwhw3gZgJJTA5eObZwSoavHS5Ksq3ZbLhNblEGaL6W-05HQzd8sE-70mfnbRmIkVRmWenxkPjfDfdDKHKM_t7DI_NicSvf3jUf1oPAhXQCFSFQJz5523aKTnnVpguyNL3Zu5H68Mj2lh7p4cm9A63-7xWCHk6YbuTwJoVoBiVGmBs2PFAmc8dhhFiXbsQoSGu_M58zf-xP6eVZZ25bw0X2HwAFEtxeZ2JJigbgaeTLCysfw7kyFr1l-fl1r60Bs9KygWzfpXjhAOlcsrlLR8Wt5Bg8PLB3ANhMvLMhuWYzURJtseicOLWuhP2mWufs-vq4rObrCGX-B3AjT1bOpjFzCJpUyx5vm2UGivMyifQNqESpAEZkUyYv-sNwYtwRrEA1EGxASA0O1D-I_48b0T3MZVvDbZmgsGZ21RTvImUdT9JSptxa5bmWa6hu72oIocy9nbJ_OX5Y9ru7pXy3AZkywOEViWsBtGJEg5naveSibHGIUcL-cVEFf-FIBVe1dRx2aUFTVoDDAMAekXwY9yEgglrbvv9WVal62y4q5Y_E8t6pLma995l00iu-YOCIvYPzsQpaiG1bFjkIi_49ahsLPJWHbrHmMCRAMvg-_Rnf9U50Q8kbFrlwCoC46C0I_6cJSQBLdgzbwX6hL9m3hsVwGmnb3kQ85xpM6CCDGaw-EQGqCNXJyxwGXPeoHJYgHPj2oOoo6KZu7mQC8JjSn6AjZwflwQR_ZnT1AIjoZPxVOF_OJv2_MZuobWeS572yC0aDnJuLpwTVtXsAhltBTc_jDqV4HDLegf5AoFcnRf_IqF2-4qmpe_VGY-9uAWN9WjLqD6JQqutQZjMlXmio4E4BQGfIhWJh_0emeX.PmfS0ZO32PcyNrhRCjzdbQ"
    }
]
"""

def test():
    cookies_list = json.loads(cookie_json)
    cookies_dict = {}
    for c in cookies_list:
        cookies_dict[c["name"]] = c["value"]
    client = LabsFlowClient(cookies_dict)
    
    # Enable test logs if we want
    client.auto_recaptcha = False # Disable generating recaptcha token to easily see the API request payload & auth status first 
    
    print("1. Fetching access token...")
    if not client.fetch_access_token():
        print("-> Failed to fetch access token!")
        return
        
    print(f"-> Token fetched: {client.access_token[:30]}...")
    
    print("\n2. Submitting batch log (testing pure cookie auth)...")
    success = client.submit_batch_log("PINHOLE")
    print(f"-> batch log result: {success}")

    print("\n3. Testing API Header generation")
    try:
        headers = client._aisandbox_headers()
        print(f"Headers created: {json.dumps(headers, indent=2)}")
    except Exception as e:
        print(f"Header exception: {e}")

    # Now let's try to generate videos (mock recaptcha for a moment just to get the exact 401 payload)
    # the exact same 401 should trigger quickly
    print("\n4. Testing Generate Videos (With mock recaptcha if possible, to hit the backend)...")
    client.auto_recaptcha = True
    
    # We will just try running generate_videos. It might trigger the recaptcha browser headless.
    project_id = "c1dcc0be-bb0d-4f43-aee9-913eba57d413"
    try:
        res = client.generate_videos(
            project_id=project_id,
            tool="PINHOLE",
            user_tier="PAYGATE_TIER_TWO",
            prompt="the girl smile ",
            model_key="veo_3_1_t2v_fast_ultra",
            num_videos=1,
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE"
        )
        print("GENERATE RESULT:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
