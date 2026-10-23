use crate::startup::Diagnostics;

pub const fn name() -> &'static str {
    if cfg!(target_os = "windows") {
        "wgpu-dx12-software-preferred"
    } else {
        "glow"
    }
}

#[cfg(not(target_os = "windows"))]
pub fn options(_: &Diagnostics) -> eframe::NativeOptions {
    eframe::NativeOptions {
        renderer: eframe::Renderer::Glow,
        ..Default::default()
    }
}

#[cfg(target_os = "windows")]
pub fn options(diagnostics: &Diagnostics) -> eframe::NativeOptions {
    use eframe::egui_wgpu::{WgpuSetup, WgpuSetupCreateNew};
    use std::sync::Arc;
    let diagnostics = diagnostics.clone();
    let setup = WgpuSetupCreateNew {
        // Do not use OpenGL or inherit WGPU_BACKEND/DXC environment overrides.
        // Fxc is supplied by Windows, so no extra shader-compiler DLL is shipped.
        instance_descriptor: wgpu::InstanceDescriptor {
            backends: wgpu::Backends::DX12,
            backend_options: wgpu::BackendOptions::default(),
            ..Default::default()
        },
        native_adapter_selector: Some(Arc::new(move |adapters, surface| {
            for adapter in adapters {
                diagnostics.record(&format!("D3D12 adapter: {:?}", adapter.get_info()));
            }
            // This small utility favors Windows' WARP CPU renderer so it can
            // open even when a VM exposes only legacy OpenGL. Hardware remains
            // usable if no compatible software adapter is present.
            let adapter = adapters
                .iter()
                .filter(|adapter| {
                    surface.is_none_or(|surface| adapter.is_surface_supported(surface))
                })
                .min_by_key(|adapter| adapter.get_info().device_type != wgpu::DeviceType::Cpu)
                .ok_or_else(|| "找不到可用的 Direct3D 12 繪圖裝置（含系統軟體繪圖）".to_string())?;
            diagnostics.record(&format!("selected D3D12 adapter: {:?}", adapter.get_info()));
            Ok(adapter.clone())
        })),
        ..Default::default()
    };
    eframe::NativeOptions {
        renderer: eframe::Renderer::Wgpu,
        wgpu_options: eframe::egui_wgpu::WgpuConfiguration {
            wgpu_setup: WgpuSetup::CreateNew(setup),
            ..Default::default()
        },
        ..Default::default()
    }
}

#[cfg(all(test, target_os = "windows"))]
mod tests {
    use super::*;
    #[test]
    fn windows_uses_dx12_with_system_shader_compiler_and_adapter_selection() {
        let diagnostics = Diagnostics::initialize();
        // An assertion failure on an unattended Windows runner must not open a modal dialog.
        drop(std::panic::take_hook());
        let options = options(&diagnostics);
        assert_eq!(options.renderer, eframe::Renderer::Wgpu);
        let eframe::egui_wgpu::WgpuSetup::CreateNew(setup) = options.wgpu_options.wgpu_setup else {
            panic!("expected explicit DX12 setup")
        };
        assert_eq!(setup.instance_descriptor.backends, wgpu::Backends::DX12);
        assert!(matches!(
            setup
                .instance_descriptor
                .backend_options
                .dx12
                .shader_compiler,
            wgpu::Dx12Compiler::Fxc
        ));
        assert!(setup.native_adapter_selector.is_some());
    }
}
