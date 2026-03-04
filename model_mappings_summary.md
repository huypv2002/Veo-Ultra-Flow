# Tổng hợp Model Mappings cho Video Generation

## 1. Text to Video (T2V)

| Display Text | Model Key | Credits | Aspect |
|--------------|-----------|---------|--------|
| Fast (16:9) | veo_3_1_t2v_fast_ultra | 10 | Landscape |
| Quality (16:9) | veo_3_1_t2v | 100 | Landscape |
| Low Fast (16:9) | veo_3_1_t2v_fast_ultra_relaxed | 0 | Landscape |
| Fast (9:16) | veo_3_1_t2v_fast_portrait_ultra | 10 | Portrait |
| Quality (9:16) | veo_3_1_t2v_portrait | 100 | Portrait |
| Low Fast (9:16) | veo_3_1_t2v_fast_portrait_ultra_relaxed | 0 | Portrait |

## 2. Image to Video (I2V) - Single Image

| Display Text | Model Key | Credits | Aspect |
|--------------|-----------|---------|--------|
| Fast (16:9) | veo_3_1_i2v_s_fast_ultra_fl | 10 | Landscape |
| Quality (16:9) | veo_3_1_i2v_s_landscape | 100 | Landscape |
| Low Fast (16:9) | veo_3_1_i2v_s_fast_ultra_relaxed | 0 | Landscape |
| Fast (9:16) | veo_3_1_i2v_s_fast_portrait_ultra_fl | 10 | Portrait |
| Quality (9:16) | veo_3_1_i2v_s_portrait | 100 | Portrait |
| Low Fast (9:16) | veo_3_1_i2v_s_fast_portrait_ultra_relaxed | 0 | Portrait |

## 3. Reference/Integrate to Video (R2V) - Multiple Images

| Display Text | Model Key (for payload) | T2V Model (for set_model_key) | Credits | Aspect |
|--------------|------------------------|-------------------------------|---------|--------|
| Fast (16:9) | veo_3_1_r2v_fast_landscape_ultra | veo_3_1_t2v_fast_landscape_ultra | 10 | Landscape |
| Quality (16:9) | veo_3_1_r2v_fast | veo_3_1_t2v_landscape | 100 | Landscape |
| Low Fast (16:9) | veo_3_1_r2v_fast_landscape_ultra_relaxed | veo_3_1_t2v_fast_landscape_ultra_relaxed | 0 | Landscape |
| Fast (9:16) | veo_3_1_r2v_fast_portrait_ultra | veo_3_1_t2v_fast_portrait_ultra | 10 | Portrait |
| Quality (9:16) | veo_3_1_r2v_fast_portrait | veo_3_1_t2v_portrait | 100 | Portrait |
| Low Fast (9:16) | veo_3_1_r2v_fast_portrait_ultra_relaxed | veo_3_1_t2v_fast_portrait_ultra_relaxed | 0 | Portrait |

## 4. Start+End to Video (SE)

| Display Text | Model Key | Credits | Aspect |
|--------------|-----------|---------|--------|
| Fast (16:9) | veo_3_1_i2v_s_fast_ultra_fl | 10 | Landscape |
| Quality (16:9) | veo_3_1_i2v_s_landscape | 100 | Landscape |
| Low Fast (16:9) | veo_3_1_i2v_s_fast_ultra_relaxed | 0 | Landscape |
| Fast (9:16) | veo_3_1_i2v_s_fast_portrait_ultra_fl | 10 | Portrait |
| Quality (9:16) | veo_3_1_i2v_s_portrait | 100 | Portrait |
| Low Fast (9:16) | veo_3_1_i2v_s_fast_portrait_ultra_relaxed | 0 | Portrait |

## 5. Expand + Reference

Sử dụng model R2V tương tự như Integrate to Video.

## Model Keys đầy đủ từ API

### T2V Models
- veo_3_1_t2v_fast_ultra (Landscape, 10 credits)
- veo_3_1_t2v_fast_ultra_relaxed (Landscape, 0 credits)
- veo_3_1_t2v (Landscape, 100 credits)
- veo_3_1_t2v_fast_landscape_ultra (Landscape, 10 credits)
- veo_3_1_t2v_fast_landscape_ultra_relaxed (Landscape, 0 credits)
- veo_3_1_t2v_landscape (Landscape, 100 credits)
- veo_3_1_t2v_fast_portrait_ultra (Portrait, 10 credits)
- veo_3_1_t2v_fast_portrait_ultra_relaxed (Portrait, 0 credits)
- veo_3_1_t2v_portrait (Portrait, 100 credits)

### I2V Models
- veo_3_1_i2v_s_fast_ultra_fl (Landscape, 10 credits)
- veo_3_1_i2v_s_fast_ultra_relaxed (Landscape, 0 credits)
- veo_3_1_i2v_s_landscape (Landscape, 100 credits)
- veo_3_1_i2v_s_fast_landscape_ultra_fl (Landscape, 10 credits)
- veo_3_1_i2v_s_fast_landscape_ultra_fl_relaxed (Landscape, 0 credits)
- veo_3_1_i2v_s_fast_portrait_ultra_fl (Portrait, 10 credits)
- veo_3_1_i2v_s_fast_portrait_ultra_relaxed (Portrait, 0 credits)
- veo_3_1_i2v_s_portrait (Portrait, 100 credits)

### R2V Models (Integrate/Reference)
- veo_3_1_r2v_fast_landscape_ultra (Landscape, 10 credits)
- veo_3_1_r2v_fast_landscape_ultra_relaxed (Landscape, 0 credits)
- veo_3_1_r2v_fast (Landscape, 100 credits)
- veo_3_1_r2v_fast_portrait_ultra (Portrait, 10 credits)
- veo_3_1_r2v_fast_portrait_ultra_relaxed (Portrait, 0 credits)
- veo_3_1_r2v_fast_portrait (Portrait, 100 credits)
