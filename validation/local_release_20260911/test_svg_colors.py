import sqlite3,unittest,xml.etree.ElementTree as ET
import navigation_settings as n,auth_access

class SvgColorTests(unittest.TestCase):
    def test_editor_metadata_normalization(self):
        source='''<?xml version="1.0" encoding="utf-8"?>
        <!-- Generator: Adobe Illustrator -->
        <svg version="1.1" id="Layer_1" xmlns="http://www.w3.org/2000/svg"
             xmlns:xlink="http://www.w3.org/1999/xlink"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
             inkscape:version="1.2" viewBox="0 0 24 24">
          <g id="layer1" inkscape:label="Layer 1" inkscape:groupmode="layer">
            <path id="path1" fill="#f00" d="M1 1h2"/>
          </g>
        </svg>'''
        result=n.icon_preview(source)['source_svg']
        for removed in ['version','Generator','id=','xmlns','inkscape','Layer']:
            self.assertNotIn(removed,result)
        self.assertEqual(ET.fromstring(result).find('g/path').get('fill'),'#f00')
        self.assertEqual(n.icon_preview(result)['source_svg'],result)
    def test_metadata_does_not_hide_unsafe_content(self):
        for content in ['<script/>','<foreignObject/>','<path onclick="x()"/>',
                        '<path href="https://bad"/>','<path fill="url(#x)"/>',
                        '<path style="position:fixed"/>','<metadata><script/></metadata>']:
            with self.subTest(content=content),self.assertRaises(ValueError):
                n.sanitize_svg('<svg version="1.1" id="root">'+content+'</svg>')
        with self.assertRaisesRegex(ValueError,'Заборонений атрибут: enable-background'):
            n.sanitize_svg('<svg version="1.1" enable-background="new 0 0 24 24"/>')
    def test_safe_paints_and_shapes(self):
        for paint in ['#f00','#ff00aa','#12345678','rgb(1, 2, 3)','rgba(1,2,3,0.5)','hsl(120, 100%, 50%)','currentColor','none']:
            svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{paint}" stroke="blue"><g opacity=".5"><rect x="1" y="2" width="20" height="20" rx="2" ry="3" fill-opacity="0.4" stroke-opacity=".8"/><ellipse cx="5" cy="5" rx="2" ry="3"/></g></svg>'
            result=n.icon_preview(svg)
            root=ET.fromstring(result['svg']);self.assertEqual(root.get('fill'),paint)
            self.assertIn('fill:'+paint,root.get('style'))
    def test_modes_preserve_original_and_storage(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close);n.migrate(con)
        source='<svg><path fill="#ff0000" d="M1 1h2"/><circle fill="blue" stroke="none" r="2"/></svg>'
        saved=n.save_icon(con,{'name':'Test','icon_key':'test_color','svg':source,'color_mode':'currentColor'},'test')
        self.assertIn('#ff0000',saved['source_svg']);self.assertNotIn('#ff0000',saved['svg'])
        self.assertEqual(n.list_icons(con)['items'][0]['svg'],saved['svg'])
        other=n.save_icon(con,{'name':'Test','icon_key':'test_color','svg':saved['source_svg'],'color_mode':'original'},'test')
        self.assertIn('#ff0000',other['svg']);self.assertEqual(con.execute('SELECT COUNT(*) FROM navigation_icons').fetchone()[0],1)
    def test_security_and_specific_messages(self):
        cases=[('<svg><script/></svg>','Заборонений елемент: script'),('<svg><foreignObject/></svg>','Заборонений елемент: foreignObject'),
               ('<svg onclick="x()"/>','Заборонений атрибут: onclick'),('<svg href="https://example.com"/>','Заборонене зовнішнє посилання'),
               ('<svg xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="//bad"/>','Заборонене зовнішнє посилання'),
               ('<svg style="position:fixed"/>','Заборонена CSS-властивість: position'),('<svg><defs><linearGradient/></defs></svg>','Заборонений елемент: defs')]
        for svg,message in cases:
            with self.subTest(svg=svg),self.assertRaisesRegex(ValueError,message):n.sanitize_svg(svg)
        for svg in ['<!DOCTYPE svg [<!ENTITY x "x">]><svg/>','<svg fill="url (#foo)"/>','<svg fill="javas&#99;ript:alert(1)"/>','<svg xmlns="http://www.w3.org/1999/xhtml"/>','<svg><image href="data:x"/></svg>','<svg fill="red;stroke:blue"/>']:
            with self.subTest(svg=svg),self.assertRaises(ValueError):n.sanitize_svg(svg)
    def test_legacy_outline(self):
        row={'svg':'<svg aria-hidden="true" focusable="false"><path d="M1 1h2"/></svg>'}
        self.assertIn('fill:none;stroke:currentColor',n.stored_icon(row)['svg'])
    def test_illustrator_presentation_subset(self):
        result=n.icon_preview('<svg><path style="opacity:0.5;fill:#B4E1ED;enable-background:new    ;"/></svg>')['source_svg']
        self.assertNotIn('enable-background',result)
        self.assertEqual(ET.fromstring(result).find('path').get('opacity'),'0.5')
        source='<svg style="enable-background:new 0 0 128 128;" xml:space="preserve"><path fill="blue" style="fill:#A15D38;stroke:#B0BEC5;stroke-width:3;stroke-linecap:round;stroke-miterlimit:10;opacity:0.35"/></svg>'
        root=ET.fromstring(n.icon_preview(source)['source_svg'])
        self.assertEqual(root.attrib,{})
        self.assertEqual(root.find('path').get('fill'),'#A15D38')
        self.assertEqual(root.find('path').get('stroke-miterlimit'),'10')
        self.assertNotIn('style',root.find('path').attrib)
        for style in ['fill:url(https://bad)','fill:expression(x)','fill:red!important',
                      'fill:red;filter:url(#x)','enable-background:url(https://bad)',
                      'stroke-width:3px!important','fill:var(--x)']:
            with self.subTest(style=style),self.assertRaises(ValueError):
                n.sanitize_svg('<svg style="'+style+'"/>')
    def test_preview_admin_only(self):
        self.assertEqual(auth_access.permission_key('POST','/api/admin/navigation-icons/preview'),'admin.manage')

if __name__=='__main__':unittest.main()
