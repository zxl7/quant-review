<script setup lang="ts">
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
</script>

<template>
  <div class="dragon-page">
    <div class="card dragon-card" data-page="dragonTiger" id="sec-dragon-tiger">
      <div class="card-header">
        <div>
          <div class="card-title">游资龙虎榜</div>
          <div class="dragon-subtitle">按原 HTML 语法嵌入通达信龙虎榜</div>
        </div>
        <div class="card-badge">TDX</div>
      </div>

      <div id="autore" class="dragon-raw-toolbar">
        <a href="https://page1.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz.html?color=##tdxbk##" target="fx"><span style="color:#FF0000">龙虎榜单</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E6%9C%BA%E6%9E%84%E4%B8%93%E7%94%A8&color=&bkcolor=undefined" target="fx"><span style="color:#F5F5F5">机构专用</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E9%99%88%E5%B0%8F%E7%BE%A4&color=&bkcolor=undefined" target="fx"><span style="color:#FFA500">陈小群</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E6%B6%88%E9%97%B2%E6%B4%BE&color=&bkcolor=undefined" target="fx"><span style="color:#FF00FF">佛山系</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E9%87%8F%E5%8C%96%E6%89%93%E6%9D%BF&color=&bkcolor=undefined" target="fx"><span style="color:#FF0000">消闲派</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E8%B5%B5%E8%80%81%E5%93%A5&color=&bkcolor=undefined" target="fx"><span style="color:#FFD700">赵老哥</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E7%82%92%E8%82%A1%E5%85%BB%E5%AE%B6&color=&bkcolor=undefined" target="fx"><span style="color:#F5F5F5">炒股养家</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E7%AB%A0%E7%9B%9F%E4%B8%BB&color=&bkcolor=undefined" target="fx"><span style="color:#FF00FF">章盟主</span></a>
        <a href="https://page1.tdx.com.cn:7615/site/tdxf10/gg_jyds_yybmx.html?style=undefined&mmbz=m&ispc=0&yybname=%E5%9B%BD%E6%B3%B0%E6%B5%B7%E9%80%9A%E8%AF%81%E5%88%B8%E8%82%A1%E4%BB%BD%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E4%B8%8A%E6%B5%B7%E9%9D%99%E5%AE%89%E5%8C%BA%E6%96%B0%E9%97%B8%E8%B7%AF%E8%AF%81%E5%88%B8%E8%90%A5%E4%B8%9A%E9%83%A8" target="fx"><span style="color:#FFD700">新闸路</span></a>
        <a href="https://page1.tdx.com.cn:7615/site/tdxf10/gg_jyds_yybmx.html?style=undefined&mmbz=m&ispc=0&yybname=%E4%B8%9C%E5%90%B4%E8%AF%81%E5%88%B8%E8%82%A1%E4%BB%BD%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E8%8B%8F%E5%B7%9E%E7%9B%B8%E5%9F%8E%E5%A4%A7%E9%81%93%E8%AF%81%E5%88%B8%E8%90%A5%E4%B8%9A%E9%83%A8" target="fx"><span style="color:#FF0088">余哥</span></a>
        <a href="https://page1.tdx.com.cn:7615/site/tdxf10/gg_jyds_yybmx.html?style=undefined&mmbz=m&ispc=0&yybname=%E5%9B%BD%E6%B3%B0%E6%B5%B7%E9%80%9A%E8%AF%81%E5%88%B8%E8%82%A1%E4%BB%BD%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E4%B8%8A%E6%B5%B7%E6%9D%BE%E6%B1%9F%E5%8C%BA%E4%B8%AD%E5%B1%B1%E4%B8%9C%E8%B7%AF%E8%AF%81%E5%88%B8%E8%90%A5%E4%B8%9A%E9%83%A8" target="fx"><span style="color:#F5F5F5">中山东</span></a>
        <a href="https://page1.tdx.com.cn:7615/site/tdxf10/gg_jyds_yybmx.html?style=undefined&mmbz=m&ispc=0&yybname=%E5%8D%8E%E6%B3%B0%E8%AF%81%E5%88%B8%E8%82%A1%E4%BB%BD%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E8%8B%8F%E5%B7%9E%E5%90%B4%E4%B8%AD%E5%A4%A7%E9%81%93%E8%AF%81%E5%88%B8%E8%90%A5%E4%B8%9A%E9%83%A8" target="fx"><span style="color:#FFD700">宁波桑田路</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E6%AC%A2%E4%B9%90%E6%B5%B7%E5%B2%B8&color=&bkcolor=undefined" target="fx"><span style="color:#FF0000">上塘路</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E5%91%BC%E5%AE%B6%E6%A5%BC&color=&bkcolor=undefined" target="fx"><span style="color:#f99fFF">六一路</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E4%B8%8A%E5%A1%98%E8%B7%AF&color=&bkcolor=undefined" target="fx"><span style="color:#FFA500">呼家楼</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E5%AE%81%E6%B3%A2%E6%A1%91%E7%94%B0%E8%B7%AF&color=&bkcolor=undefined" target="fx"><span style="color:#F5F5F5">欢乐海岸</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E6%B2%AA%E8%82%A1%E9%80%9A%E4%B8%93%E7%94%A8&color=&bkcolor=undefined" target="fx"><span style="color:#FFD700">沪股通专用</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E6%B7%B1%E8%82%A1%E9%80%9A%E4%B8%93%E7%94%A8&color=&bkcolor=undefined" target="fx"><span style="color:#FF0088">深股通专用</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E4%BD%9B%E5%B1%B1%E7%B3%BB&color=&bkcolor=undefined" target="fx"><span style="color:#F5F5F5">量化打板</span></a>
        <a href="https://page.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz_yz.html?flag=yzxq&code=%E9%87%8F%E5%8C%96%E5%9F%BA%E9%87%91&color=&bkcolor=undefined" target="fx"><span style="color:#FFA500">量化基金</span></a>
      </div>

      <iframe
        id="sl"
        class="dragon-raw-frame"
        name="fx"
        src="https://page1.tdx.com.cn:7615/site/kggx/tk_yzlhb_yz.html"
        marginwidth="1"
        marginheight="0"
        border="0"
        frameborder="0"></iframe>
    </div>

    <ShortReminderFooter />
  </div>
</template>
