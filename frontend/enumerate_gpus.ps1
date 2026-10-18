Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class GpuEnum
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DXGI_ADAPTER_DESC
    {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        public string Description;
        public uint VendorId;
        public uint DeviceId;
        public uint SubSysId;
        public uint Revision;
        public UIntPtr DedicatedVideoMemory;
        public UIntPtr DedicatedSystemMemory;
        public UIntPtr SharedSystemMemory;
        public long AdapterLuid;
    }

    [ComImport, Guid("770aae78-f26f-4dba-a829-253c83d1b387"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDXGIFactory1
    {
        void SetPrivateData(ref Guid Name, uint DataSize, IntPtr pData);
        void SetPrivateDataInterface(ref Guid Name, IntPtr pUnknown);
        void GetPrivateData(ref Guid Name, ref uint pDataSize, IntPtr pData);
        void GetParent(ref Guid riid, out IntPtr ppParent);
        void EnumAdapters(uint Adapter, out IntPtr ppAdapter);
        void MakeWindowAssociation(IntPtr WindowHandle, int Flags);
        void GetWindowAssociation(IntPtr WindowHandle, out int pFlags);
        void CreateSwapChain(IntPtr pDevice, IntPtr pDesc, out IntPtr ppSwapChain);
        void CreateSoftwareAdapter(IntPtr Module, out IntPtr ppAdapter);
        void EnumAdapters1(uint Adapter, out IntPtr ppAdapter);
        void IsCurrent(out int pCurrent);
    }

    [ComImport, Guid("29038f61-3839-4626-91fd-086879011a05"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IDXGIAdapter1
    {
        void SetPrivateData(ref Guid Name, uint DataSize, IntPtr pData);
        void SetPrivateDataInterface(ref Guid Name, IntPtr pUnknown);
        void GetPrivateData(ref Guid Name, ref uint pDataSize, IntPtr pData);
        void GetParent(ref Guid riid, out IntPtr ppParent);
        void EnumOutputs(uint Output, out IntPtr ppOutput);
        void GetDesc(out DXGI_ADAPTER_DESC pDesc);
        void CheckInterfaceSupport(ref Guid InterfaceName, out long pUMDVersion);
        void GetDesc1(out DXGI_ADAPTER_DESC pDesc);
    }

    [DllImport("dxgi.dll")]
    public static extern int CreateDXGIFactory1(ref Guid riid, out IntPtr ppFactory);

    public static void Run()
    {
        Guid iidFactory = new Guid("770aae78-f26f-4dba-a829-253c83d1b387");
        IntPtr pFactory;
        int hr = CreateDXGIFactory1(ref iidFactory, out pFactory);
        if (hr != 0) return;
        var factory = (IDXGIFactory1)Marshal.GetObjectForIUnknown(pFactory);
        for (uint i = 0; ; i++)
        {
            IntPtr pAdapter = IntPtr.Zero;
            try { factory.EnumAdapters1(i, out pAdapter); }
            catch { break; }
            if (pAdapter == IntPtr.Zero) break;
            var adapter = (IDXGIAdapter1)Marshal.GetObjectForIUnknown(pAdapter);
            DXGI_ADAPTER_DESC desc;
            adapter.GetDesc(out desc);
            ulong dvm = desc.DedicatedVideoMemory.ToUInt64();
            Console.WriteLine(i + "|" + desc.VendorId.ToString("X4") + "|" + desc.Description + "|" + (dvm / (1024u * 1024u)));
            Marshal.ReleaseComObject(adapter);
            Marshal.Release(pAdapter);
        }
        Marshal.ReleaseComObject(factory);
        Marshal.Release(pFactory);
    }
}
"@

[GpuEnum]::Run()
