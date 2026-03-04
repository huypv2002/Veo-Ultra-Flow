import argparse

import json

import time

from typing import Any, Dict, List, Optional, Tuple

import requests



# --- Bagian 1: Ambil token reCAPTCHA ---

recaptcha_cookies = {

    '_Secure-3PAPISID': '2UeOQXOodsu_VYj0/Aad8MAmN4-IytTwUs',

    'NID': '527=iewRR20n1ePPRcnwpI37ndYrbCgaHX3UdN4P7mb4G7-srTZAMdzNUlps_9rLCp_8WhBrG-Q_j_zo2fPeoQ3oHQbxJjcW_DR3fBpnRfngZjoN7_J9OEC4K6FvQNYCocgF-an2mTlIGOUD2GuAv8TAsxCPxw3wAbCWGvXiwmpFijWgTSET7n4rLk3woP8HQj6fNyVOKKcVp1oD3MLvAr08DO7ilE8s42dsvf4x9LaLcopxxDVDnZgGNixyAXa6l8T51J-73mA2GMHxEblvDFhS_azIklsbnxaT62k-TY5yWcyrufCXVf3K-0ItdPDhLGckhvkge2ad3R0DC9HE49v5nJmi523tU4KjaB2lF5WBEnZxlXq4_sFVL6bXiYsBawdPUyqelcaRyvgCJ42eu3CZVkrjPZwUaNnhETGXH-aQ6rTS9p3U4tHXTVdMOvMXP53SHvruU0g4OZysYR9N3J2H-zTaPHfcFF0ti91G2ZUw4ao2Fq4nbajHHON8TcDAKp9NAtsAFb3TkY3Njbe7CO8JpSGFdNk12oCNdwf_ePAnXFv3etQmxN8FMHMIj1qaustjszhfT_3UyW4ZaAnlle8miNf7fP0Qj1oqeJGuUeUjPSY1cz5JK49uRZAp9HUY2aM8uUWmjqZkfLma0PZaavtsJkFnCkgfizri6TYY6DlWdgyWtGyGrwYoeXuuoxxPFVbCerxdns-eOXXmmdRe6I1HHWZC8H2tkReofAtyzvSo',

    '_Secure-3PSIDTS': 'sidts-CjIBflaCdd9AVSJbi4rCnuuYfaAz7HUdQz2Lz5dExlon4pQZXC23JmYY_5Lr7MtxYbUOJxAA',

    '_Secure-3PSID': 'g.a0004gh6rMoTcVRUtDVy-0Xf3iCUHAqt3L_vQOWL1zBdLqxIv17n6rFo8ynfHk5H1d1pySzVsQACgYKAW4SARQSFQHGX2MiSTV5Whd6xuXSumZXfj6rUhoVAUF8yKp9wTa21AH55loASydiAFMf0076',

    '_Secure-3PSIDCC': 'AKEyXzWN1i8eM25x_QWS4ae4bLdrLhTgqjoWFzUp9TjDbtq9kZiLmmUN1ppXYSwoq7gVMIY9hg'

}



recaptcha_headers = {

    'accept': '*/*',

    'accept-language': 'en-US,en;q=0.9',

    'content-type': 'application/x-protobuffer',

    'origin': 'https://www.google.com',

    'priority': 'u=1, i',

    'referer': 'https://www.google.com/recaptcha/enterprise/anchor?ar=1&k=6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV&co=aHR0cHM6Ly9sYWJzLmdvb2dsZTo0NDM.&hl=en&v=7gg7H51Q-naNfhmCP3_R47ho&size=invisible&anchor-ms=20000&execute-ms=15000&cb=mhbvzuv4acfy',

    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',

    'sec-ch-ua-mobile': '?0',

    'sec-ch-ua-platform': '"Windows"',

    'sec-fetch-dest': 'empty',

    'sec-fetch-mode': 'cors',

    'sec-fetch-site': 'same-origin',

    'sec-fetch-storage-access': 'active',

    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',

    'x-browser-channel': 'stable',

    'x-browser-copyright': 'Copyright 2025 Google LLC. All Rights reserved.',

    'x-browser-validation': 'UujAsOGAwdnCJ9nvrswZ+0+oco0=',

    'x-browser-year': '2025',

    'x-client-data': 'CO/oygE=',

}



recaptcha_params = {

    'k': '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV',

}



recaptcha_data = (
    '\x187gg7H51Q-naNfhmCP3_R47ho\x12\x8e\x0c03AFcWeA6snsWvQsT_QJni-Hv2_fQkwYRGNwFUxXIaQKKUZSV2YZfp6BmM7qxWVZzRpHNuHQBViJIRgx-RxVeqoEgWCELt5R83kOVMhuOmoZXvJ_hDnk8cEKDldc3-b8o7LGz1eUhBIMOCYUtFlG1uyBxclpGo5qkRwe6HEHdK5XE9mmIO5dQapZhSPTqwcjHyL3eIDr1indGtdBThPnqX1Q7krmHmKhG_rdQfA0IdDgNKkCDLdRUgtTJkSY4l__kL8CPvA7aqxiS7sXnXN1gZvUJnXUODRAuccLetZHkm4fV1f3W1lwYw8JDn3LC6qE8wzhJHmyaFE967ine7uwA0yhz36nSaIg7lypuogJE5-RUAwF4a5LJi3piBm6JuV_joeq1Up9J8MymsdWuWplaH5TxhhxO4wUHtMANAKXgYsapRTJKK_X8vnD_fVeyOb_6wI8CvgaBAVxTue0FqLFwKgJa02RbuK_ZRFX0ZlB8A6FPctNPWTpGRQMUmsK74heO6A48yPgxFAHkxkaFzygCP0ZviuL0nG6gu34IM7-KP_y1kWQ0zJ3q57DDxo1GJNWe9MAyJnu8nVyjtYFyg9r4LoMn3JQyZcpmzRua2Xn7d5EsEIYKrbgkPbilleC0hDuFFrPSPik_4rGpHR0-rw6tc0aVB6OX6wUM4PLSxwUw2CN9mYUggG6-EGMEPh0zeoKTXihIHPJYo1yPb1gqrLt3ogUHDPh1yFAaPOQokh22WnUgy1nnj49VU4U49oH6wSrg6L2aEZ3JH7xzelJhh052hfrlHhyGUp4-l6hPD9EF3uuhAm6Nb_T30_uPCIbpBaEYmpOXegu503JeNPsQ3Bx2-xLDi44Bp28tSKRDejlt4sGd7sh_rF9GQ87AqFnPGUMgCeV14kbThSSveC5bQDq30Eu9gXDT-MI0SWGUVJl0LjmVcI1D2ObsdF2kTlxiKB69x4ErOBxqTctMtVYUBRn_VPmk9f4wMcVHHBn3dtzuXV-NqPJIZZaOjnFrRrv2q7LkNi9KcGDcvtkAVYm4kxDjucwLUIOBhSYBIhT69eRhOmDPK_waEPskJadRl-Au3Xp3Ee8L2ljfBrgf7e6CqmZhZoFJIwaMbu4TJvAzx7HWS-90zI8kL8NNI-7yaRkSJchrIFRbzdDVlpCHElywf1RMdQD4TzAA1XF7LrCNWzWu_0HOF9YTL3Po03AAnMxkAJevRkpY9hIvjUl3qh_TmENBkW0wbSyaWHH2qmO8MzUXk-vW6u61_jN2VRkHoiO9N9SprRd32YB7YkYXOjHi9b2_z_cRT42OdHp2zgrxPXz1onwPK26TEHqAwnoJyyGnMxnjCOudWEerEtAD-Bob0iZMWjQo8_Y656A3QyFNl6NeLsBx3DZDa4Rei3b2LxB9GULYFL3HXclY-jJviaSE9x1BBUOa4ClDXtV2t9N8XrYplIFudjyr3Ly3hlB-pJ_nRVY8dSuOzj6EonEv6xGkLfDnsZ99NJJcfCCa-L6y5mKT0iwOmUSSs9d3tdimbDeoks7K8NIsNhzwV-qM0\"\xdc\x0c!e32gfXgKAAQeFuEobQEHewEwC4agf824jjka_jVDIMPh_Bx3GSa5mOpcB0-nHwLwJqw42DLI0thqd5U6GvPgKc7xd6847bnO6C4cxdweJ6gApcJIQ0KR0t2QQBco--L1MriSelq3pQKigWTgHZVG4P7hSxvu2rg-40L5Oh-Q0yjycBgMzMHu_lcHCwXUFEqC383KTRFS376WRLPTAfeOYdSH9eqrERUmEi20FkpTyTPM_4q7a35qwDhWXK0cuJpcCWBYU_9IAkcgHs9hA5_QhdAk3Xv9IcsSt1RqXaNo82riWC9x_LNuH4d0UWOXHO6UlN2hv7F4YzVjlUKWdX-53rCygFXh2AO5-f4Ow7PCn_ynHjSL45PS-Aj2x_N0ayyEpehqYlzXuQQ1K5DFSvKuNwW8WQYdy1F6NZfFnO0kOybW5JwDf-1SwBIKZslgWBXwuqexM-crl8C6qoyv7q0sVLwFwadzzjXlU2iONkB6l0b4kGZbQbLikSJpLoQUJ_drpcE7a8uhu4OVZppA6UoSAdu3Qqlsk3Rc5Tf2UCZpKkVqpodGl-t5NYWXANlcNKpVy2IE6tI03nYeiXMw6MRURQk7gxCoFr7fiqbhdR9HCFQbGWBFSDFDhv_RPhiK_2NoEFq-N1iwoeIJgofkPddeThNKo29I7zyBKVSdsMSR96L8mwaR_yDOsQrKK6snegR5MbT6WWMphc8KN3eZnBIYMp-zOEcsEqf2K6nUsjrgrEKbjdlO15_gwoc2J18ODuOQWWKAXKySPawnyAwPQUIzkA8jLZ5NZVX_pKAaciOR6Khep2_h4W-j5EFsrOOjviEdfNlhEeUhXHTRsww69eEDJs6Hwy3AIu-bbslcmZRWqjFkqffkTHa8w4OIm5M_vlGBhIhFN0k69v1QL31wQg_iAP7sCLxR7cTK2daZyrZDtpak6C52v15dSYEjfKV2nnppOyBOatQozB5RUHXrwv4b8oKCwvsLVPIbu4tkpivgfXii6PcvOgAh_3OdXeBui9UH8bIv-WuGkj416YvoCkKdB-mVEuxBj4cpynlnx8Gg16eHmX8DbgHMT_vmp0u-crzzLMfzyAq6VUWi-bG1sheDO46FZZobO4NrUP3QSM6k5HAXADYiqpnhz48ade1LOT4TEYQtcZJ9pWdnF2gTzMbKUYUoMIXG2dIHhMFSbHcqUR_lMWimu5NHfb1YZNw1vzzbDImASYUzdtHuG-WZ5iM6I9OPFW_69xi2_piOMr6gUJR5zHnvM4x2LfmPUcyCO3xg26jz3hkHl7GKTN1CgiO3YDxcSU1cj8A4zSLLLtH3X5SZFAvzJNGHw24RVindoRi_z-NwT4rGj3yVfrt4PQamh2GVzq_nhuvvtARC1lECm6me8OQ96tSa27VEJLnVyrK_9eC5UERljwduIbZVBM61HuZrF3aoIP9Rot3uWd8Zwc8ph5mp91hiK28B5JxTSjBHntjQ5bjgUIVgdpHJEQqdy2zPJM0VNUNF1TYK_zCR8343eO20ucuvlPaxMQsBZBJyJwJje_GEM1TOaxVC63Vx3xLdbI0QsBh4itFP8sm1CcKFJQbB98eumKMkDH0l0aUwydf61ziaWsMx8mdk3AfXC8iZz5s*\x095535970362\x01qB\x0fFLOW_GENERATIONr(6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV\x82\x01\xfc.0xuhu6FLF-K0nkQQ37GbQQ3YrpQ-CtR6oErcsXdpVwHXvWcz_tC6YCz7zbddKfTKsFom8cetVyPuwKpQHOu9p00Z5LqgShbht51HE96wmkAM22BKvCMD-ndiGyVXFE7w-gvGWxjzTL8VMfed6BnL7Lswzsi2KDXHEa8IefStt5lO8WtdN4Ce6K6z0X-VtviuI_KEBYNMrqF3XQbTnnBaA8ybbVb8yZRqU_nGkWdM9sOOYEnzvItdRuy5hFpD6baBCfC-N5Xz7T-pJsDyS8nsJigJw1SWHMYoDZP9T4kOnTLPzgfZax26uWagRnfSM2UfgMKUVpiac30LzQ8INkCxk-GvZRb0rmhCVHYjdYfYkpgi5BXjlX9hU2BvCCqLmWtk40TzDBLkieAaC_kqbF7IJaQ0_vDStH437eO5Z-DrcFsk9fzqo9G3EIZ4YjQBx3VrQOtocvvirE5zYe_hlyBWWKZMkbwoopR-XBX3kYddD4SPF_7Icd8tIwDioG4cEeuSExmiiVZwRji2hHpHMUKEqxByC-Xe4Na8imwh08WbacbNVj0K19p3ycOlw7UWWHpMbmdaGszuuP7D3ahiUvk_rX7IbiSugyXDjR9ApkAuHCTm2LqYTiPVy51ryNNYQwwiI3FnRSbcxmBWK_ZXXebNmrSKfErIvX-VgxzvVLJMGhslGwDOsGYUCd-mCxGagU6dRmzRy01-5VsQbwRmD95DaS79guhab21jQSrwxlxSJ-JTWeLJl102dSZcsSsc_tyiYBoP4aQNF5yHUMpwuYN1Xyj2yHJkOfRlb_Tfqbr8DgPhw4Fa_PLEfvP6g2o32UqYjnROI-WLfVMFfoUN9MJsbScZAuCOYBYL3ZAJE5iDTMMwXbQNlB1jhHNo6niShBXMBQ48MhPpy5E_JOa8ikf168GL6PN4Yy0KR-5z8db5O1mGwMpnjbe5l0161RXsXZQVIvjbGKqsvjeBY-VzvM9UssB2k72vMKbgshB6G22_-V6gjrRmw-HHzQdg9sQ61JIAePLkzqxaL-HXqV_U37GbQQ3YYUgVf9S3nKKcerCSL6UqnM8NFaOVd1Em3JKEXhCFjBT_yZe0LiAJ65VrHRLklxAao4pX4fvB2vzzADYECWQtC1T_PI37-mvdOvDTPOJoIjAKL91TANs4rvBx98IbITrAex_WJ_1HfZMpCyie4F23MgMk9yiGeKXcdhMw2xVSqNYEBfd5atV28SL4dZ_l602WmTLkRehqG5F3lV8kjluqCBVrrXZwnsSac9F_yWMZeoAKr1VLLPLIklwyC72jWQ8M2qUCCJF4RbNYqpx-YDHzmY9hE4yXaVL4xZAZA803YG6Y3qCadvju1JZwLh_Vo3k-5OacZtvia1IfmWsFItEO6FnUWbPtJ3kS-Fm0nZuxN0TCsC3MukxBU92jPH70UjSRu0kqvW6UxoxuXA1G3Z5w5rDqdFXrQVelarzmUAIvKc7Y1rwd6NHPmjspSoibJM4cdbAQ4uka1BpwQju6B1la-DZksrd-A5XvHNcxFlgyh5YfFKcVGpgBU0Um9MKIVjAF26VzCQrAhvwGj3ZD5a9Vlrlmo6GXdV8o6qiOQBHzpVtVCuFOVN3EkevlosC2lHYr_bOlfy2mrTYc6qjVT0Eq8NqkPjAJtDE7wKt1Rk068JpITNbIsnROL8W7hUu4w0gy_M4YteeiGu1e9M5QTgtlL8GO5Xc8OqCmd5HP1Ibwerf-U1lvSSLFVyBGl_JnsOrtluBSl7nDSVLdG11amHHweb9VJpkvIIG_-fe516kuqI38Mg9-Q4zDpW5o3d-RrEU_NMbsgq_2D53jdTrcrwgmu2mTybt8vpQqOBKTXiec7sBCRG5AhSdU0vjW_A6UMb-Bw12DePKQRqgdkvG3jK8M2avSM7IHIMpYkk-5lAHfNKrYpwxusD2UJcb8u0QaNJ4D-Z7ZP4kS9G6QMgtQz2BemAZfmgANw9inEJZ4DlPtIAXXIJ6wrlSeW-TXBZcosnS9094v7QNgynD2b_nPrUL0jvzmMEI_qVfk4sUfFGq4TU7pmyjPFMqgZmMVSy0HIQH4WfOqH0FPnWswUgPeN3zjrQ8wtviCNCl3MXOFFxPGKIoDgNqowqBG593EEWLM8sDPAEZoNYORC6VS7DJgpdw99xkeXPsD9hNlJ7mefRJcLlCRuAm3vMNU5txFd61rwS68tmSprE4L6S-Esx0G59XsCP8w5nk6kAnwGcNNi6U2bI4QUj8c75Ti7L5Epc_FX22rXDaQfggRn2GjPZKoGjghvD3bvO9sgtvuX8YroU8AY0SORH2z_cPhH0Rq58oEIgNZJuU2cQZ8VWwxrwzWqOqYij_hL_0C4SMoSmwNf2FzdIqc0qu97AIa2YbNShfZ9FGcAQ8QIhf115VjERLdOkDJsH334Z9dfwDqpLHzQTcc_qh-MCX7picttp1qvH8H3e_FzwGTHWKAQuOVx3lH5J7s_mgt07n3NQ7k6pha45Jn5TNxhpRuSCYDqecw_vCKrNmoDmfd96DWrO70QmtBe407jUZInhRCW22m2XrUmkgFU4lezRLcbkhNkCWHMabobqx1xBlr9K6ggmAeA52TYTeQmyAK1E3AjU-xe3UGnS40fid9y8kTRNMARhdiT_nLcX3z5cuRXyUC2KZ4Rd_dl13S2WJJFyCps0U7IPKsfjQp-84rMbqhbpRbKPKwYeL5Z1l7RMpQiWeZCyFy3RMYupgmNxVnsG8EbhwCb21vYap1EtSeh-nzAcNwXphuCJ1f3gLIPjAR98WDLSLwxyAqs5pn0d9Q3zC2iGI8ti-RmyFmuJYLwpgiF2mnXGLcSqeFy-UzQas8Iv_2DB1jSXNJYohCgJEK_N68dlf5772P7Pd8ZzCakK5vbbfNsyC_FG4UNkwZZxGLJQ6ATaPqLxHGzK7rsaeFYzTmoJZkNpeeJw3bfO51Cwj-w4WzYesEzt0WlCnwAcfk6vTGdG5whfuMxlhOLA3PqUs9Dtk-RCYTvad1D5R_SLMj-hN94CXDaNckdeBlhAjWyKqIRhfFu4lTuMNIMoB2a-6MBZsxhtS-UMYPvY75iy0mW7mvjWsg8siaXB4DtXNxKvFmbPXcqiAR15Fi_WMo9wP1642H4SeUrvBGAJGIKVbg_rhOp_p_yT_glv0-SEYD2Ta4roxuI_mrnW8lnqUuFOJYeg-5gAkieTMMga_qMx2u7YawFlBuSFV7eRsBNhhhmEm7HRZcUjv9451PQRLFQkjRuIV8Lcv1Sx0ijIpMShg5d1SLGOKzsiPlc-U68RJYxfRBt8zbCLtcmuiiLzYTRPZlWhSR5AZLvWeBRrBKGKIDhVvIo2EiuDZ3dZ91DoSm7AZ4FVAJ4vlPMBbExkOVF3WTVSaMchv5vwkXxTMoiqgp99m62YL5MpPGmIG7VS9ddrS5wB5EAgPNGlSOAN3jxZ_VC3g_GQnz7eMU3y2TKSpYkffGHynCyOLX9jeKKB1bYG8g9ZOFZ0UC4IKATquyOyHvudrg8ww1vJHbgTeY40yLABabbZvc-uU-iFbIieew6mxiQCnnwV9RHu1SWOHIlgutl8WHJKdMcsSyR6VjFJ9JGwvF922W8aaM9h0OnF20BTd4jryd_LmXsYeAcmROJ-23YVcg61Re5LJ_ZcQx_6mLO_JIqpxeI8yOgCYsBc9WDxWehNc1KuiuaGYSsKZIUivxeDE7wKsld1fSI4m8SdPRdjgt092zNe-4wpxZ_J6wkjQuG9RfFB6kcohyG-SykEon4YSlyx0T2KtlCt_9g9GLKZ7oUzDaOJm_HS604piGTIoH0U8c8wxCbNKoij-BNzVW_JXfndNJR9F2SRr8MiRhl5nfYT6EUkQRTzoPwVaYwuPGi_I_wXLJItzFpElYFP-pduUawMXD_Q-tlsS2oC2HUighy5S_OI5gFnuaCxEOeJn8iotp5zGOnMow3biOKyWzmZdk5rSWG9YjcTuQdkOiW2I0HceQXzEawI1b4fvhi1QiC7mXUPfV77BycM5kUSPY47WfRRHcsphCDtmvlT8L1lx2XAXSnHo0Ec9yFCFTPRuIOlQ9j3HWzYaNY0jyv4pcRe-4hw0nDLaDTS7kwnwim-3IqaMNks2jXP3wWYP2AuFDiGMgtfPlU20CsTpItlR9y1ny6cbIVkjiA1T_tL9FX0Tuu4VrHQq0WyCrBA3kZh8001FmmQXLinuV2ziDbTpYRqNtI2C3DMJkwjuGT6Uq9XI5Ld_CaEYbvR7MkkxyI2pLYOKwfhkCYGJ7SceFWsA6iBobVefxOxV3GJIwojuhC7lvKTHwIlRZ-vl_mRbsRb-9n6H3fPI0KlviaF3S2ZrwgvRpl-nD6Wr0SxTu6J4oLZuklyjqvJXf2aQFN5yfL_7AmUdxM3SOnRHYlmNk-sT65EoUrqeF1ynDdHKkGnRyO30XqOqX9q-2PFY_5bJ8Whfxr1Jz7T69llT59D3IGb9xAyCeI_2b8icxL2x-tQ64rk9xPp1WXOb85oxZJwC-mFX4UuwmcEnzTYNs0kChl84n0cdkile2b3X8Ff-lcjwd17FvERMBh3FiNFpAajNw_0WbTGoswle-HvWCjV4Usjv2GA2fDGL4ahSeQCj7iR6dCgAhd8F3-a79bm_mx5nfmeLM9lTucFJT0WfNFplnF-VsJS-1z7VfK_XTjWsky-C-fEZn1dx9lBWTpKbREkfde-3LWX6dBbRtd_4X_adwPhvVs20TkX7BQkwuxBZjUarErtBCrB6T4Z-FFtCd_LW8RlxF77iGbB3_tVhlSxEfcVLocovN3313ka9QbmSZyHHnxMNArozlz3mvVP-4lowae_F8URd9f0TTLPIUTTeQ03D2wKLPnl_Q--W66T5Irfd-L2DXlUbE6c-Z-6HfpMZROuCJf713vcZ4XrjN_5VTrgNs6pBSV_5_XcrVJswibFYzibuY6wi-eMLoooeWAtlu_GoMJdxiBAGTrE8o7jfOS6kuzU8waqQyWCoq_cMRPwCiiBGkAS-s11hJ3-5v1f7krnyzBMWb2dMNG2CnD_YUgX9B06zu8Q7I2ewhuzE2oLIU6j-Bw_lPgI9EJigB_71bsQsYXmyuDJXfTfOIxjPuWC33LRcMk1UGxBXgXTNwxzUyq-44off1N4mneS7wpo_uEAV6lTKo_ced1yzfnWtNFeAOAAn7NX7ZXsyywIGXZW6w0yCaHIZftR9pcryizAWjRRM8q5S6dNqXuYblnqUvRS7UoW9VBuieQGpUTqCJV7T_LV9AUpi-REUD2ca8InxJ5CnTcMcNYyzWDA3sKg-Jl2gl_8JkGgbt2yxXGNbclhAV7ymm1OLMnk-qN7EO_Ir0Raw1uADfqJNIkmviU5WbULJ8Unxqh9Wfdd7swiyKSHnrqhvFM2SWSDpwHee1StCWZC40eV-FAplvWCIr_YgFZt0PmOJcGjPyBC3XcXsQYsOaVzHbnQ7ggtAysGFP4caxdvheCCXUAYOMokyGXAHwEX_hDuVPCN4giYgxyySClFIsqhQhn3U7QN7gsa_BhBDLJLtMSrBl07WjYY6BQlhCe9JLvL7obyB1uI2npUuI7xyqTEJDRjbdh1UqGCWwOUgN74lOSNH7vgtNJvWjdM8AcavhOB1S2IZJCsutrCz_ISbMzoAimDkjxdekd0DKt6ZUQT6tF10mJ-GvDcbNo4ky_8qchi_4x5mDKPXASmBJ87yKZCH_uV_9k8VfNS4okb-tryIXnRcZRvgikFWwDYLoSigZeDE7wdvBazQB35l3MNbUwvErFKLECi-Z3rEOkNpL_a85BpFKUScMtoNN1-3XfUoX8a-NRunfAS84YtPB23EH6S6MVxw6MHJEDS8FCxCeRMJX3ecI1jTuu8KUfifwv0QufHJn7mupVtmLMLpMzgSBvvUzgKpXtauhcx0G0KJwPfuho1kjlJ9xWwDNmG5X_cqVHgTSRKIDQXO4u1xS3FK72hAJrvBmLIpLhnO1C0jSWHIEAlvOP1Ve_N8LsaeNUzjyoJZgJpRg\xa2\x01\xd1\x04tbMywyOSwyODA1XSxbMSw2NCwyODU1XV0sW1syLDIzMCw1MzUuMTAwMDAwMDIzODQxOV0sWzIsMTcxLDc2NS40MDAwMDAwMzU3NjI4XSxbMiw3OCw5NTYuMzAwMDAwMDExOTIwOV0sWzIsNjEsMTIwNC4yMDAwMDAwNDc2ODM3XSxbMiwyMTAsMjIxOF0sWzIsNjEsMTkzODYuNzAwMDAwMDQ3Njg0XV0sW251bGwsbnVsbCxudWxsLFs4LDkuNzk5OTk5OTg5NTY5MTg3LDAuMDA0NjA2MDc0ODQzODEzNzMsMjRdLFs0MTEsMC4yMDQzNzk1NjExNzM2NTQ4MywwLjAwNDkzNTA4MDE3NDA0MjE5MSwzXSwwLDAsNl0sWyJ3d3cuZ3N0YXRpYy5jb20iLCJ3d3cuZ29vZ2xlLmNvbSIsImZvbnRzLmdvb2dsZWFwaXMuY29tIiwibGFicy5nb29nbGUiLCJsaDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tIiwid3d3Lmdvb2dsZXRhZ21hbmFnZXIuY29tIiwic3VwcG9ydC5nb29nbGUuY29tIl0sWzYsNTg4XV0\xaa\x01I0aADnWZkHWWFmZocUzRwa8kCPqju7gfaYuu0RN-LuSheSOet0ifJk_ZwWUVzL-Bt5xCgbJbxQ\xb2\x01\xa4\x1dBTAAYAIAHEeAAUpYIwlDCKAsCJlcgB6AAJtAggoIEEOALSoQRZ1SZyAJBHAJCmAJQYhFJESBlKAAIAEg7QBjbEBoCFZoQgoNGLKCoRGAcMQFGGIBQAYhAhYAT4CFtQiEUjolYQ65EiAXICQeQCCkQgEcQOFRZhRAYJmdAIkAQIIAkaJZocQIAQSACBwGMgACCEWoELFAFggQgJCEJcHjQg2VgFQIgABJoEAKEEBAcAQaUIzEcAdAAKgUERAgFUshGqMkkaJoYIAMysQAiXkARQAAATIAFAWGrAEAAhIyZMCxBEwRJQ04NWFwiGMCwiwtCNVSEiwBqgQEHFqNQM8LQEJJPIQWgAIrBtKOAARAygLWQEMAKGR4CIUABIxsL0RgEkQByHBhFGNzQYqAGGGDbRMQYBAADQAGADIUAMAhiMBCwgATNMoRmiCEBVQXEEAIEEwCIqgSTgaoyBnJCIpBGybFKDIEAkAgAJLRmRJUigI0m8gFAREUUJgQUiSJBSFKNA5QQxBAAFQIoBtBAHKJNUAI4EIQrCMh0ECAZICqQIMBAAQhQBBCAhQkMEKBQNJTUSqRgUTABAwAhWkUc0BDUQaiyKFFSIAm4BhEDyMAISEC4MBkiCPQQah0KMKEAIBAwIAThoKJ+UmRFEXAwQkCCCaEQsAQEQZUhEAgeBYGHWAHFIoAsGEhAhDC1EkNBwHgDpgCimRQIA0BANHQMASOIChiqBDGoCEARiCurqAIAHYBAIZoAeUQAPEgiqAAxCCpEggIExiAKCBEKQohCACoF0HSQQJQgQYqbQACYFQhVwSAQLgEqCBACE+DAyICM4IhIBEAJcNiAhTUo6RWBKESfmQE4AUQA9NgKPBDAIBoGCABBkiMACQgIUJxUihoGoFHcBpoI8gIAhQ4rYB2EBhgNBCGD7YIGCzgpAD1AIxEBJCaCgMRCfQj8GAcDtIIAAQJKEAEAMQyauIcyErLIAiBUCCECAAi0BEDQFoADBZScQL8ABgoBLAGFFpCEIDICgiAAQgihCGAlARC2VIDwh64gCQGIrKZQCBhaAlMkoGZAokQCHRIEgAKAWiAAqAVARQFUQgkCZtBI6BFAmoCAg4QDBAPEIJwAGKcK2EADMEQggA4wIoIEgKlCUqC2sBBSQRQr4ACwhEAMCwF62AgIIAWCwSwEiAeRFAIELvJTUSBFaIv4NQBwvRFAmU6mRQLLGkRChAAICVBEggWEwLwaBCuIOSBExTIjATYMoyAOMAgIAILBJUyEJB6QDAACKRCxAEwkXAiwaY0kAAgOGBHyVRUoIwIADYImLMT40swQgzAueAGs4bAGumwCDMALoESaCRgkQEFBGDgBQKM0iCwviktEjgAUNAAgIYLuGYDOgSEOUIC3CwWAVkNR2UJD4D4zAzIsKY8+YABB1KBNIgCBogAqAhOlEKqvyoSQgEAACyCDQWJQBKCEAACmICCiC1QAQzhQZBFAA0sNogIBQDFUEQhBEkGBAEQEYCBogEAjWCRIsQEAUAyCSoSCRBwgwAEvaaRaBAkxlghgYQJDIqAC0kCBjIOwgAIoBQHgnBiAQAQGICgQNIiTAGwQARAQNSFSkRUjJVdqYAopBiABFoAzQImljKErrAGqTIIA0AgSEGiQgEAAgMkDSIiECGYENWQC5yBBNkRgaAGwOIhrIKUCgACxChK9ggAgIAAIAzDTSkgAwAqgpANAA0QoACOhCIZHIUAAQYIEgaAHohFEhBgBqElAECAWDBBKSUAQYgJEBYIkLKiIBBBxAA1EKCYKAT1ECgAAEgCMgJIHjBAJcBA+UO4iOKoAVgIFASUrismMEgKAJAlwAw0IA9wEFACQAgNgkQI0BIAggVxAGCJRCRUAV0CJIh4EBbAQOAApBUAZImAEgjkoaQBFHGAELMjCLgEhlcTKEAgCsAtQYwpICUMSACOJBAgADgJIwCEAA4AyGURCApPJADikhBgwLzAgAQjQiTCQEMgEiqBk1RABAhpvWAdAJCAEAQEQghpIIBJrgtCbImCwkCvQEAUqmnBnhRLIoUAwCQgMICoEYIKBhsAEiMABgYBRIhMKQQOgQnoECAxEhpBp6BGrJkaAZCO4LsDABR1sgEjAAZA4zpcCBAEhIATQFmQwwFdAJIiAAyjBTvQCBSYBDzQBgDuDAoAYCONIAkijAAYQgomEABEE4MAZqkAUhIIAECwQCoWQzMkyNoICQQJsb34NAJRcEqA6i2jhITATC3BBJAmMAKCRBkAcAgBSDIOAISsqJLmgCBwIOWZmURQmgEBJMEQTBiUInCKAIBAhQQBIFRiKkSAXxRCMARQ4AA3AUWAhMACWgAqCCkBABKGAaAZCATYCKFE1CMCAdQGcIOkUGCgQMAQYCRkPRBIgIIoRUeUgAMNHMIAEjJABEIxgqJkDgMAGEoQIBAQMAIBkDHBgUIABgAQAEELsCyIUwEQIUtUokCkyhTQpFAqLMICAAAAgmYkmAEMMVIQQgAEqELmEGG9iFAAXGADGIOEag0ECBIIQQQyAggakAaQl5VEDClAFwggTJB2CQAAUBoBkgihEkRCAiFnQTIfwJPQgABMIEAAhB8FIIUthUgGxYBQEEQBKSNqCrIQihMbcEBRTIUMHCgYgFswJWhFcjgoABAgZpQgQohXAAxAEGJw0ECBA5LAJpLkEoZxAgAIRTUUE0GPlSEQIAcGrwAOxEAJEIBKBTAzsIyABAGIIaYA0gGDMA0QIkBQQAgcCoDZsBQiKKhMQDKEQhihHmQKtPFES4zCFLpAhwjgOUIAQVkCRECAAA0IQAGOJGFBBQw1ESh4QQEGJCCIVkuWBkpqCAFCRaxIDDQlFBoj3DjAIAYyMAesNAMQpJAMmGNPShAShAkERwAAMoGqroQGAEocAsABGwjmwCCAFDIUBAAgCE2AQBQnBAJgBAAEFJDwANDREFkekMBmVgADKSaBlIgKlSCGSMOBzCQIG6anAQBAPEBRBEgBgIES4ITLJvA+BgjSI5AxKgoAhGEEmUikJAMAWJR0gm0IIdYAB0AdAiEpMU4CgAqBYAQYoGAKACCH5CMWqIMAnAAgCCEBYGEEJAUAm6BKQViAg4IkTyABFKKeLDGmGRsCQgpBGnLoIAjDKEAQUEkBBHKDABQgBIDM4EgCIEBIxYFB4AspAwAAAJQIgZQ6aChKA4uxGGtTggCAXAKYBsTEAgooG/8WRigBQjAJEQYgBBQThDDJEUCgQpxYwgARVxCBQnTDAGEAUxANBREcFpTwgtiRDAgAAwH4LII5bGJQnxgcJQA2ACkLQXhJwZUQAXUTFDAIQCgaEDDAiTtAABgyCJ3gAAQxEAENA8RAhEAUKDZgMkQWkAnCDZjIAAhNHJsAzqQQ5CgCVAlRAoFFQvCSpSYpkAogIIwQXNFCR0ICjcGDkLaiDQQGIEmggABMSCBnCgAiiIlmWBAjtJOAIYJUJEEQAAOcpWgpmBKBgsoBuENoT2iKiggiCUoFgSIGD8IwAyEKCn0gDgRRSAioIRAAAg3RGOMcE4s0WEjJAlLiYAAgAPIIwUBKB0ABUIgbhniGCEMAMgAgMBBIAhQA0YzAgEmAgoopkC0iIbgsjgfh0FYARBwQiM0BoDFIC0EwWBogFVXOgpEQUE1NBnkBawAICWRwYiBrRAI4JEMlLA4wHozVg5AYhEBaAnoKCreDQgBACYAkhEBVADDAeiNAVBUBNtVAjU0OBQijJlPAhaFUADIqARmZSAKgD4CI\xca\x01VW1tbNTAwNiw0ODRdLFs2NDYwNyw0XSxbMzU4MzcsNF0sWzQ1NDY0LDRdLFszMTYxNywzXSxbMzcxNzgsM11dXQ\xe0\x01 \x9c\x01\xe8\x01\xb0\xea\x01'
).encode('latin-1')



def get_recaptcha_token() -> Tuple[Optional[str], Optional[int]]:

    try:

        response = requests.post(

            'https://www.google.com/recaptcha/enterprise/reload',

            params=recaptcha_params,

            cookies=recaptcha_cookies,

            headers=recaptcha_headers,

            data=recaptcha_data,

            timeout=30

        )

        

        print(f"Status code: {response.status_code}")

        

        if response.status_code != 200:

            print(f"Error response: {response.text[:500]}")

            return None, None

        

        raw = response.text.strip()

        print(f"Response length: {len(raw)}")

        print(f"Response preview: {raw[:200]}...")

        

        # Remove XSSI prefix )]}' if present

        if raw.startswith(")]}'"):

            raw = raw[4:].strip()

            print("Removed XSSI prefix )]}'")

        

        token: Optional[str] = None

        ttl: Optional[int] = None

        payload: Any = None

        

        # Try to parse JSON from different positions

        for candidate in (raw, raw[raw.find("["):] if "[" in raw else None):

            if not candidate:

                continue

            try:

                payload = json.loads(candidate)

                print(f"Successfully parsed JSON: {type(payload)}")

                print(f"Full payload: {payload}")

                break

            except Exception as e:

                print(f"JSON parse error: {e}")

                continue

        

        if payload is None:

            print("Could not parse response as JSON")

            return None, None

        

        if isinstance(payload, list) and len(payload) > 1:

            token = payload[1]

            if token is None:

                print("WARNING: Token is null in response. Possible reasons:")

                print("  - Cookies may be expired or invalid")

                print("  - recaptcha_data may need to be refreshed")

                print("  - Request may be blocked by Google")

                return None, None

            

            if len(payload) > 3 and isinstance(payload[3], int):

                ttl = payload[3]

            print(f"Token extracted successfully: {token[:50]}...")

        else:

            print(f"Unexpected payload format: {type(payload)}, length: {len(payload) if isinstance(payload, (list, dict)) else 'N/A'}")

        

        return token, ttl

    except Exception as e:

        print(f"Exception in get_recaptcha_token: {e}")

        import traceback

        traceback.print_exc()

        return None, None



# --- Bagian 2: Kirim permintaan video ---

video_headers = {

    'accept': '*/*',

    'accept-language': 'en-US,en;q=0.9',

    'authorization': 'Bearer YOUR_TOKEN_HERE',

    'content-type': 'application/json',

    'origin': 'https://labs.google',

    'priority': 'u=1, i',

    'referer': 'https://labs.google/',

    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',

    'sec-ch-ua-mobile': '?0',

    'sec-ch-ua-platform': '"Windows"',

    'sec-fetch-dest': 'empty',

    'sec-fetch-mode': 'cors',

    'sec-fetch-site': 'cross-site',

    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',

    'x-browser-channel': 'stable',

    'x-browser-copyright': 'Copyright 2025 Google LLC. All Rights reserved.',

    'x-browser-validation': 'UujAsOGAwdnCJ9nvrswZ+0+oco0=',

    'x-browser-year': '2025',

    'x-client-data': 'CO/oygE=',

}



def build_video_payload(recaptcha_token: str) -> Dict[str, Any]:

    return {

        "clientContext": {

            "recaptchaToken": recaptcha_token,

            "sessionId": ";1765992307723",

            "projectId": "3e364a17-7a48-4b93-9b8d-c3af801f8053",

            "tool": "PINHOLE",

            "userPaygateTier": "PAYGATE_TIER_TWO",

        },

        "requests": [

            {

                "aspectRatio": "VIDEO_ASPECT_RATIO_LANDSCAPE",

                "seed": 10345,

                "textInput": {

                    "prompt": "lion tiger ingin ikut lomba lari meski semua menertawakannya"

                },

                "videoModelKey": "veo_3_1_t2v_fast_ultra_relaxed",

                "metadata": {

                    "sceneId": "bbdfe990-1376-42c5-b364-aa099775fc8b"

                }

            }

        ]

    }



def main() -> None:

    parser = argparse.ArgumentParser(description="Generate video dan polling status.")

    parser.add_argument("--recaptcha-token", help="Token reCAPTCHA manual (jika tidak ingin ambil otomatis)")

    parser.add_argument("--bearer", help="Override Authorization Bearer token untuk video request")

    parser.add_argument("--sitekey", help="Override nilai k (sitekey) untuk recaptcha")

    

    args = parser.parse_args()

    

    if args.sitekey:

        recaptcha_params["k"] = args.sitekey

        # Perlu diselaraskan juga referer/anchor jika sitekey berubah.

        print(f"Sitekey diganti ke: {args.sitekey}")

    

    if args.recaptcha_token:

        token = args.recaptcha_token

        ttl = None

        print("Memakai recaptcha token manual.")

    else:

        token, ttl = get_recaptcha_token()

        if not token:

            print("Gagal mengambil recaptcha token.")

            return

        print(f"Token reCAPTCHA: {token[:40]}... (TTL: {ttl}s)" if ttl else f"Token reCAPTCHA: {token[:40]}...")

    

    payload = build_video_payload(token)

    if args.bearer:

        video_headers["authorization"] = f"Bearer {args.bearer}"

    

    resp = requests.post(

        'https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoText',

        headers=video_headers,

        json=payload,

    )

    

    try:

        initial = resp.json()

    except ValueError:

        print(resp.text)

        return

    

    print("Response submit:")

    print(json.dumps(initial, indent=2))

    

    operations: List[Dict[str, Any]] = []

    for item in initial.get("operations", []):

        op = item.get("operation", {}).get("name")

        scene = item.get("sceneId")

        if op and scene:

            operations.append({"operation": {"name": op}, "sceneId": scene})

    

    if not operations:

        print("Tidak ada operasi dikembalikan.")

        return

    

    check_url = "https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus"

    for attempt in range(20):

        time.sleep(5)

        check_resp = requests.post(

            check_url,

            headers=video_headers,

            json={"operations": operations},

        )

        try:

            data = check_resp.json()

        except ValueError:

            print(f"Polling {attempt+1}: {check_resp.text}")

            continue

        

        print(f"Polling {attempt+1}:")

        print(json.dumps(data, indent=2))

        

        statuses = []

        for item in data.get("operations", []):

            status = item.get("status", {}).get("status")

            if status:

                statuses.append(status)

        

        if statuses and all(s == "MEDIA_GENERATION_STATUS_SUCCESSFUL" for s in statuses):

            print("Semua operasi sukses.")

            break

    else:

        print("Polling selesai tanpa semua status SUCCESSFUL.")



if __name__ == "__main__":

    main()



